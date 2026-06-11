import asyncio
import json
import uuid
from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from config import ACCESS_PASSWORD
from auth import verify_token, get_expected_token
from database import (
    init_db, create_task, get_task, get_task_by_bvid, 
    get_all_tasks, delete_task, reset_task, update_task_status
)
from downloader import extract_bvid
from queue_worker import download_queue, active_tasks, download_worker_loop, transcribe_worker_loop, diarize_worker_loop
from progress import progress_manager

app = FastAPI(title="bili2text 视频语音转录系统")

# 允许跨域（本地开发调试方便）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 启动生命周期事件：初始化数据库并开启后台 Worker 线程/协程
@app.on_event("startup")
async def startup_event():
    init_db()
    
    # 恢复因重启中断的任务
    tasks = get_all_tasks()
    for t in tasks:
        if t["status"] in ["pending", "processing"]:
            print(f"检测到中断任务，重新排队: {t['id']}")
            reset_task(t["id"])
            download_queue.put_nowait(t["id"])
            
    # 每个阶段各启动 2 个 Worker 协程消费对应队列，实现多任务流水线并行处理
    for _ in range(2):
        asyncio.create_task(download_worker_loop())
        asyncio.create_task(transcribe_worker_loop())
        asyncio.create_task(diarize_worker_loop())

@app.on_event("shutdown")
async def shutdown_event():
    print("正在优雅关闭服务，取消所有后台运行任务...")
    for task_id, task in list(active_tasks.items()):
        task.cancel()
    # 等待一小会儿让 CancelledError 有时间在 event loop 里面抛出并完成清理
    await asyncio.sleep(0.5)

# 1. 登录验证
@app.post("/api/auth/login")
async def login(data: dict):
    password = data.get("password")
    if not ACCESS_PASSWORD:
        return {"token": get_expected_token()}
        
    if password == ACCESS_PASSWORD:
        return {"token": get_expected_token()}
        
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="锁屏密码输入不正确，请重试"
    )

# 2. 提交转录任务
@app.post("/api/tasks")
async def submit_task(data: dict, authorized: bool = Depends(verify_token)):
    url = data.get("url")
    lang = data.get("language", "zh")
    asr_model = data.get("asr_model", "whisper-large-v3")
    transcribe_source = data.get("transcribe_source", "bili_ai")
    
    if asr_model not in ["whisper-large-v3", "whisper-large-v3-turbo"]:
        raise HTTPException(status_code=400, detail="不支持的语音识别模型")
        
    if not url:
        raise HTTPException(status_code=400, detail="请输入 B 站视频链接或 BV 号")
        
    try:
        bvid = extract_bvid(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    # 防重复机制：在数据库中查重
    existing = get_task_by_bvid(bvid)
    if existing:
        status_curr = existing["status"]
        if status_curr in ["pending", "processing"]:
            raise HTTPException(
                status_code=400, 
                detail=f"该视频目前处于[{status_curr}]排队中或处理中，请勿重复提交！"
            )
        elif status_curr == "completed":
            raise HTTPException(
                status_code=400, 
                detail="该视频已在历史记录中转录完成，点击左侧记录即可直接查看，无需重复消耗 API 额度！"
            )
        elif status_curr == "failed":
            # 如果之前的任务失败了，我们允许重新录入，这里我们先删除之前失败的记录再创建
            delete_task(existing["id"])
            
    # 创建新任务
    task_id = str(uuid.uuid4())
    create_task(task_id, f"https://www.bilibili.com/video/{bvid}", bvid, lang, asr_model, transcribe_source)
    
    # 投递入后台第一阶段下载队列
    download_queue.put_nowait(task_id)
    
    return {"task_id": task_id, "status": "pending"}

# 3. 获取所有历史任务列表
@app.get("/api/tasks")
async def list_tasks(authorized: bool = Depends(verify_token)):
    return get_all_tasks()

# 4. 获取特定任务详情
@app.get("/api/tasks/{task_id}")
async def get_task_detail(task_id: str, authorized: bool = Depends(verify_token)):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="未找到该转录记录")
    return task

# 5. 删除特定任务
@app.delete("/api/tasks/{task_id}")
async def remove_task(task_id: str, authorized: bool = Depends(verify_token)):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="未找到该转录记录")
        
    tasks_to_cancel = [k for k in list(active_tasks.keys()) if k.startswith(task_id)]
    for key in tasks_to_cancel:
        print(f"检测到活跃任务 {key} 被删除，正在强制取消运行中的协程 Task...")
        active_tasks[key].cancel()
        
    delete_task(task_id)
    return {"message": "记录删除成功"}

# 6. SSE 实时进度推送
# 因为浏览器 EventSource 无法通过 Header 传 Bearer Token
# 所以支持通过 URL Query 参数传递 token 进行安全性验证
@app.get("/api/tasks/{task_id}/sse")
async def task_progress_sse(task_id: str, token: str = Query(None)):
    if ACCESS_PASSWORD:
        expected_token = get_expected_token()
        if token != expected_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="未授权的连接"
            )
            
    async def event_generator():
        async for data in progress_manager.subscribe(task_id):
            yield f"data: {json.dumps(data)}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# 8. 获取特定任务详细日志
@app.get("/api/tasks/{task_id}/log")
async def get_task_log(task_id: str, token: str = Query(None)):
    if ACCESS_PASSWORD:
        expected_token = get_expected_token()
        if token != expected_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="未授权的连接"
            )
            
    log_file = Path(__file__).resolve().parent / "logs" / f"{task_id}.log"
    if not log_file.exists():
        raise HTTPException(status_code=404, detail="未找到该任务的详细日志")
    return FileResponse(str(log_file), media_type="text/plain; charset=utf-8")

# 9. 重试转录失败的任务
@app.post("/api/tasks/{task_id}/retry")
async def retry_task(task_id: str, authorized: bool = Depends(verify_token)):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="未找到该转录记录")
        
    if task["status"] != "failed":
        raise HTTPException(status_code=400, detail="只有转录失败的任务才可以重试")
        
    # 如果该任务已经在运行映射中，先取消并清理它（包含所有带有后缀的协程）
    tasks_to_cancel = [k for k in list(active_tasks.keys()) if k.startswith(task_id)]
    for key in tasks_to_cancel:
        print(f"检测到失败任务 {key} 重试，正在取消残留的协程 Task...")
        active_tasks[key].cancel()
        active_tasks.pop(key, None)
        
    # 重置数据库状态，清空 error_msg, raw_result, result 字段并变回 pending
    reset_task(task_id)
    
    # 重新放入第一阶段下载队列
    download_queue.put_nowait(task_id)
    
    # 向客户端推送初始化进度
    progress_manager.publish(task_id, {
        "step": "parse",
        "msg": "正在重新排队分析视频...",
        "progress": 10
    })
    
    return {"message": "已重新塞入转录队列", "status": "pending"}

@app.post("/api/tasks/{task_id}/retry_llm")
async def retry_llm(task_id: str, payload: dict, authorized: bool = Depends(verify_token)):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    source = payload.get("source", "bili_ai")
        
    update_task_status(task_id, "processing")
    
    # 向客户端推送初始化进度
    progress_manager.publish(task_id, {
        "step": "diarize_and_merge",
        "msg": f"正在为 {source} 重新排队大模型推理...",
        "progress": 85,
        "has_raw": True
    })
    
    from queue_worker import diarize_queue
    diarize_queue.put_nowait((task_id, source))
    return {"message": "已重新塞入大模型推理队列", "status": "processing"}

# 7. 静态文件托管
static_path = Path(__file__).resolve().parent / "static"
static_path.mkdir(exist_ok=True)

# 挂载静态资源路由
app.mount("/static", StaticFiles(directory="static"), name="static")

# 首页重定向到 static/index.html
@app.get("/")
async def read_index():
    index_file = static_path / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "bili2text 服务已运行。请在根目录下创建 static 静态资源包。"}
