import asyncio
import traceback
import os
import json
from database import update_task_status, update_task_metadata, get_task, update_task_raw_result
from downloader import get_video_metadata, download_audio, delete_temp_file
from transcriber import transcribe_audio_raw, diarize_and_merge_segments
from progress import progress_manager

# 全局多阶段队列
download_queue = asyncio.Queue()
transcribe_queue = asyncio.Queue()
diarize_queue = asyncio.Queue()

# 全局正在活跃进行中的任务 Task 映射
active_tasks = {}

async def handle_task_error(task_id: str, e: Exception):
    """
    统一转录流程异常错误处理
    """
    traceback.print_exc()
    err_msg = str(e)
    
    # 将错误及其堆栈追写进日志
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{task_id}.log")
    try:
        with open(log_file, "a", encoding="utf-8") as lf:
            lf.write("========================================================================\n")
            lf.write("=== 错误信息: 转录任务失败 ===\n")
            lf.write("========================================================================\n")
            lf.write(f"异常信息: {err_msg}\n")
            lf.write(f"堆栈信息:\n{traceback.format_exc()}\n")
    except Exception as log_ex:
        print(f"写入错误堆栈到日志失败: {log_ex}")
        
    # 将任务标为失败，写入错误日志
    update_task_status(task_id, "failed", error_msg=err_msg)
    progress_manager.publish(task_id, {
        "step": "failed",
        "msg": f"转录失败: {err_msg}",
        "progress": 100
    })

async def do_download(task_id: str):
    """
    步骤一：下载音频轨道
    """
    task = get_task(task_id)
    if not task:
        print(f"任务不存在: {task_id}")
        return
        
    bvid = task["bvid"]
    try:
        # 1. 改变任务状态为处理中，解析视频元数据
        update_task_status(task_id, "processing")
        progress_manager.publish(task_id, {
            "step": "parse", 
            "msg": "正在向 B 站提取视频元数据...", 
            "progress": 10
        })
        
        # 爬取标题与简介
        meta = await get_video_metadata(bvid)
        title = meta["title"]
        desc = meta["description"]
        update_task_metadata(task_id, title, desc)
        
        # 2. 下载音频轨
        progress_manager.publish(task_id, {
            "step": "download", 
            "msg": "正在连接 B 站视频流...", 
            "progress": 20
        })
        
        def on_download_progress(percent: int):
            total_progress = 20 + int(percent * 0.4)
            progress_manager.publish(task_id, {
                "step": "download",
                "msg": f"正在极速下载音频轨 ({percent}%)...",
                "progress": total_progress
            })
            
        audio_path = await download_audio(bvid, on_download_progress)
        
        # 投递至下一阶段 transcribe_queue
        await transcribe_queue.put((task_id, audio_path))
        
    except asyncio.CancelledError:
        print(f"任务 {task_id} 在下载阶段被用户强制取消。")
        # 强行中断时，确保清除未完成的临时文件
        delete_temp_file(f"temp_audio/{bvid}.m4a")
        raise
    except Exception as e:
        await handle_task_error(task_id, e)

async def do_transcribe(task_id: str, audio_path: str):
    """
    步骤二：ASR 语音识别并落库草稿
    """
    try:
        task = get_task(task_id)
        if not task:
            print(f"任务不存在: {task_id}")
            return
            
        lang = task["language"]
        asr_model = task.get("asr_model") or "whisper-large-v3"
        
        progress_manager.publish(task_id, {
            "step": "transcribe_raw",
            "msg": f"音频下载成功！正在调用 {asr_model} 进行语音识别 (第一阶段)...",
            "progress": 65
        })
        
        raw_segments = await transcribe_audio_raw(audio_path, lang, task_id=task_id, asr_model=asr_model)
        
        # 将第一阶段的原始结果存入数据库
        update_task_raw_result(task_id, raw_segments)
        
        progress_manager.publish(task_id, {
            "step": "diarize_and_merge",
            "msg": "语音识别完成，正在通过大模型进行角色分离与智能合并 (第二阶段)...",
            "progress": 85,
            "has_raw": True  # 通知前端已经有草稿可以查看了
        })
        
        # 投递至下一阶段 diarize_queue
        await diarize_queue.put(task_id)
        
    except asyncio.CancelledError:
        print(f"任务 {task_id} 在转录阶段被用户强制取消。")
        raise
    except Exception as e:
        await handle_task_error(task_id, e)
    finally:
        # ASR 结束时（无论成功、失败还是取消），立即无痕销毁本地音频文件释放磁盘空间
        if audio_path:
            delete_temp_file(audio_path)

async def do_diarize(task_id: str):
    """
    步骤三：大模型角色合并与剧本排版
    """
    try:
        task = get_task(task_id)
        if not task:
            print(f"任务不存在: {task_id}")
            return
            
        raw_result_str = task.get("raw_result")
        if not raw_result_str:
            raise Exception("未找到原始语音识别草稿结果，大模型无法合并。")
            
        raw_segments = json.loads(raw_result_str)
        
        final_segments = await diarize_and_merge_segments(raw_segments, task_id=task_id)
        
        progress_manager.publish(task_id, {
            "step": "postprocess",
            "msg": "角色合并成功！正在保存最终剧本...",
            "progress": 95
        })
        
        update_task_status(task_id, "completed", result_dict=final_segments)
        
        # 推送最终完成状态
        progress_manager.publish(task_id, {
            "step": "completed",
            "msg": "转录完成！",
            "progress": 100
        })
        
    except asyncio.CancelledError:
        print(f"任务 {task_id} 在大模型合并阶段被用户强制取消。")
        raise
    except Exception as e:
        await handle_task_error(task_id, e)

# ----------------- Workers 常驻消费协程 -----------------

async def download_worker_loop():
    while True:
        task_id = await download_queue.get()
        try:
            print(f"[Queue Worker] 下载阶段取出任务: {task_id}")
            task = asyncio.create_task(do_download(task_id))
            active_tasks[task_id] = task
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Download worker 循环异常: {e}")
        finally:
            active_tasks.pop(task_id, None)
            download_queue.task_done()

async def transcribe_worker_loop():
    while True:
        item = await transcribe_queue.get()
        task_id, audio_path = item
        try:
            print(f"[Queue Worker] 识别阶段取出任务: {task_id}")
            task = asyncio.create_task(do_transcribe(task_id, audio_path))
            active_tasks[task_id] = task
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Transcribe worker 循环异常: {e}")
        finally:
            active_tasks.pop(task_id, None)
            transcribe_queue.task_done()

async def diarize_worker_loop():
    while True:
        task_id = await diarize_queue.get()
        try:
            print(f"[Queue Worker] 合并阶段取出任务: {task_id}")
            task = asyncio.create_task(do_diarize(task_id))
            active_tasks[task_id] = task
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Diarize worker 循环异常: {e}")
        finally:
            active_tasks.pop(task_id, None)
            diarize_queue.task_done()
