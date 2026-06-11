import asyncio
import traceback
import os
import json
import requests
from database import update_task_status, update_task_metadata, get_task, update_task_raw_result, update_task_result
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
    步骤一：获取 B 站 AI 字幕 或 下载音频轨道
    """
    task = get_task(task_id)
    if not task or task["status"] not in ["pending", "processing"]:
        print(f"任务不存在或状态不适合下载，跳过: {task_id}")
        return
        
    bvid = task["bvid"]
    source = task.get("transcribe_source", "whisper")  # bili_ai, whisper, dual
    
    try:
        update_task_status(task_id, "processing")
        progress_manager.publish(task_id, {
            "step": "parse", 
            "msg": "正在向 B 站提取视频元数据...", 
            "progress": 10
        })
        
        meta = await get_video_metadata(bvid)
        title = meta["title"]
        desc = meta["description"]
        update_task_metadata(task_id, title, desc)
        
        # 如果需要获取 B 站 AI 字幕
        if source in ["bili_ai", "dual"]:
            progress_manager.publish(task_id, {"step": "parse", "msg": "正在尝试提取 B 站官方 AI 字幕...", "progress": 15})
            try:
                from bilibili_api import video, Credential
                import json
                try:
                    cookies = json.load(open('cookies.json'))
                    cookie_dict = {c['name']: c['value'] for c in cookies}
                except Exception:
                    cookie_dict = {}
                    
                cred = Credential(
                    sessdata=cookie_dict.get('SESSDATA', ''),
                    buvid3=cookie_dict.get('BUVID3', ''),
                    bili_jct=cookie_dict.get('bili_jct', '')
                )
                v = video.Video(bvid=bvid, credential=cred)
                info = await v.get_info()
                subs = await v.get_subtitle(info['cid'])
                
                if subs and subs.get('subtitles') and len(subs['subtitles']) > 0:
                    sub_url = subs['subtitles'][0]['subtitle_url']
                    if not sub_url.startswith('http'):
                        sub_url = 'https:' + sub_url
                    r = requests.get(sub_url)
                    d = r.json()
                    bili_segments = []
                    for i in d.get('body', []):
                        bili_segments.append({"start": i['from'], "end": i['to'], "text": i['content']})
                    
                    if bili_segments:
                        update_task_raw_result(task_id, "bili_ai", bili_segments)
                        progress_manager.publish(task_id, {"step": "parse", "msg": "B 站 AI 字幕提取成功！", "progress": 20, "has_raw": True})
                        await diarize_queue.put((task_id, "bili_ai"))
                        
                        if source == "bili_ai":
                            return  # 单独的 AI 字幕模式，跳过音频下载与 Whisper 转录
                else:
                    raise Exception("未找到官方 AI 字幕")
            except Exception as e:
                print(f"获取 B 站 AI 字幕失败: {e}")
                if source == "bili_ai":
                    raise Exception(f"未能获取到 B 站 AI 字幕 (可能不存在或风控): {e}")
                else:
                    progress_manager.publish(task_id, {"step": "parse", "msg": "B 站 AI 字幕提取失败，继续进行本地转录...", "progress": 18})

        # 下载音频轨 (针对 whisper 和 dual 模式，或者 auto 回退)
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
            
        cancel_flag = {"cancelled": False}
        def check_cancel():
            return cancel_flag["cancelled"]
            
        audio_path = await download_audio(bvid, on_download_progress, check_cancel)
        await transcribe_queue.put((task_id, audio_path))
        
    except asyncio.CancelledError:
        print(f"任务 {task_id} 在下载阶段被用户强制取消。")
        cancel_flag["cancelled"] = True
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
        if not task or task["status"] != "processing":
            return
            
        lang = task["language"]
        asr_model = task.get("asr_model") or "whisper-large-v3"
        
        progress_manager.publish(task_id, {
            "step": "transcribe_raw",
            "msg": f"音频下载成功！正在调用 {asr_model} 进行语音识别 (第一阶段)...",
            "progress": 65
        })
        
        raw_segments = await transcribe_audio_raw(audio_path, lang, task_id=task_id, asr_model=asr_model)
        
        update_task_raw_result(task_id, "whisper", raw_segments)
        
        progress_manager.publish(task_id, {
            "step": "diarize_and_merge",
            "msg": "语音识别完成，正在通过大模型进行角色分离与智能合并 (第二阶段)...",
            "progress": 85,
            "has_raw": True
        })
        
        await diarize_queue.put((task_id, "whisper"))
        
    except asyncio.CancelledError:
        print(f"任务 {task_id} 在转录阶段被用户强制取消。")
        raise
    except Exception as e:
        await handle_task_error(task_id, e)
    finally:
        if audio_path:
            delete_temp_file(audio_path)

async def do_diarize(task_id: str, source: str):
    """
    步骤三：大模型角色合并与剧本排版
    """
    try:
        task = get_task(task_id)
        if not task or task["status"] != "processing":
            return
            
        raw_result_str = task.get("raw_result")
        if not raw_result_str:
            raise Exception("未找到原始语音识别草稿结果，大模型无法合并。")
            
        raw_segments_all = json.loads(raw_result_str)
        raw_segments = raw_segments_all.get(source)
        if not raw_segments:
            raise Exception(f"未找到来源为 {source} 的草稿数据。")
        
        progress_manager.publish(task_id, {
            "step": "postprocess",
            "msg": f"正在处理 {source} 数据角色合并...",
            "progress": 90
        })
        
        final_segments = await diarize_and_merge_segments(raw_segments, task_id=task_id)
        
        update_task_result(task_id, source, final_segments)
        
        task_latest = get_task(task_id)
        source_mode = task_latest.get("transcribe_source", "whisper")
        raw_res = json.loads(task_latest.get("raw_result") or "{}")
        final_res = json.loads(task_latest.get("result") or "{}")
        
        is_completed = False
        if source_mode == "dual":
            whisper_done = "whisper" in final_res
            bili_ai_expected = "bili_ai" in raw_res
            bili_ai_done = "bili_ai" in final_res
            if bili_ai_expected:
                is_completed = whisper_done and bili_ai_done
            else:
                is_completed = whisper_done
        else:
            is_completed = True
            
        if is_completed:
            update_task_status(task_id, "completed")
            progress_manager.publish(task_id, {
                "step": "completed",
                "msg": "转录排版完成！",
                "progress": 100
            })
        else:
            progress_manager.publish(task_id, {
                "step": "postprocess",
                "msg": f"{'B站AI字幕' if source == 'bili_ai' else '本地语音'} 已完成大模型转换，等待另一路完成...",
                "progress": 95,
                "has_final": True
            })
        
    except asyncio.CancelledError:
        print(f"任务 {task_id} 在大模型合并阶段被用户强制取消。")
        raise
    except Exception as e:
        print(f"任务 {task_id} 的 {source} 来源大模型排版失败: {e}")
        update_task_result(task_id, source, [{"error": str(e)}])
        
        task_latest = get_task(task_id)
        source_mode = task_latest.get("transcribe_source", "whisper")
        raw_res = json.loads(task_latest.get("raw_result") or "{}")
        final_res = json.loads(task_latest.get("result") or "{}")
        
        is_completed = False
        if source_mode == "dual":
            whisper_done = "whisper" in final_res
            bili_ai_expected = "bili_ai" in raw_res
            bili_ai_done = "bili_ai" in final_res
            if bili_ai_expected:
                is_completed = whisper_done and bili_ai_done
            else:
                is_completed = whisper_done
        else:
            is_completed = True
            
        if is_completed:
            update_task_status(task_id, "completed")
            progress_manager.publish(task_id, {
                "step": "completed",
                "msg": "转录排版结束 (部分失败)",
                "progress": 100
            })
        else:
            progress_manager.publish(task_id, {
                "step": "postprocess",
                "msg": f"{'B站AI字幕' if source == 'bili_ai' else '本地语音'} 大模型排版失败，等待另一路完成...",
                "progress": 95,
                "has_final": True
            })

# ----------------- Workers 常驻消费协程 -----------------

async def download_worker_loop():
    while True:
        task_id = await download_queue.get()
        try:
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
        item = await diarize_queue.get()
        task_id, source = item
        try:
            task = asyncio.create_task(do_diarize(task_id, source))
            # 为了防止双路并发时 ID 冲突，使用复合 key 存入 active_tasks 也可以，但通常没关系因为它们是顺序消费或不同时报错的
            task_key = f"{task_id}_{source}"
            active_tasks[task_key] = task
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Diarize worker 循环异常: {e}")
        finally:
            active_tasks.pop(f"{task_id}_{source}", None)
            diarize_queue.task_done()
