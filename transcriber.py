import httpx
import asyncio
import mimetypes
import os
import json
import shutil
import re
from config import (
    GROQ_API_KEY, LONGCAT_API_KEY, CORRECTION_GLOSSARY,
    GROQ_API_BASE, LONGCAT_API_BASE, HTTP_PROXY, HTTPS_PROXY
)

def get_httpx_client(timeout: float = 150.0, use_proxy: bool = True) -> httpx.AsyncClient:
    """
    统一获取带代理配置的 httpx 客户端
    """
    if use_proxy:
        proxy_url = HTTPS_PROXY or HTTP_PROXY
        if proxy_url:
            return httpx.AsyncClient(proxy=proxy_url, timeout=timeout)
    return httpx.AsyncClient(timeout=timeout)

def format_time(seconds: float) -> str:
    """
    将秒数格式化为 [MM:SS] 或 [HH:MM:SS] 格式
    """
    if seconds is None:
        return "00:00"
    
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def filter_hallucinations(segments: list) -> list:
    """
    清洗过滤 Whisper 语音识别中常见的广告幻觉和背景噪音
    """
    # 需要在文本中直接擦除的幻觉文本模式
    erase_patterns = [
        r"请不吝点赞\s*订阅\s*转发\s*打赏支持明镜与点点栏目",
        r"请不吝点赞\s*订阅\s*转发\s*打赏支持",
        r"请不吝点赞\s*订阅\s*转发",
        r"请不吝点赞",
        r"打赏支持明镜与点点栏目",
        r"打赏支持明镜与点点",
        r"明镜与点点",
        r"订阅\s*转发\s*打赏支持",
        r"yoyoyo",
        r"yo\s+yo\s+yo",
    ]
    
    cleaned = []
    for seg in segments:
        text = seg.get("text", "")
        original_text = text
        
        # 逐个擦除幻听词
        for pattern in erase_patterns:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)
            
        # 移除可能遗留的开头/结尾的多余空格和标点（比如擦除后开头剩下了逗号或句号）
        text = text.strip()
        # 清除开头多余的标点符号，如 ", ", ". ", "，", "。"
        text = re.sub(r'^[，。；：,.?!?\s]+', '', text)
        text = text.strip()
        
        # 如果擦除后 text 变空，或者只剩下极短的无意义字符，我们就过滤掉这整个 segment
        if not text or len(text) <= 1:
            print(f" -> [过滤幻听] 剔除整段空白或无效段落: [{seg.get('start')} - {seg.get('end')}] 原始文本: '{original_text}'")
            continue
            
        # 如果文本发生了部分擦除，更新 seg 中的 text
        if text != original_text:
            print(f" -> [过滤幻听] 部分擦除幻觉文本: [{seg.get('start')} - {seg.get('end')}] 原文: '{original_text}' -> 现文: '{text}'")
            seg["text"] = text
            
        cleaned.append(seg)
        
    return cleaned

async def transcribe_single_chunk(chunk_path: str, language_mode: str, asr_model: str = "whisper-large-v3") -> list:
    """
    对单个音频分片进行语音识别上传，配备 5 次重试机制以耐受代理抖动
    """
    if not GROQ_API_KEY:
        raise ValueError("未配置 GROQ_API_KEY，请检查服务端 .env 文件并完成配置。")
        
    if not os.path.exists(chunk_path):
        raise FileNotFoundError(f"找不到需要转录的音频分片: {chunk_path}")
        
    mime_type, _ = mimetypes.guess_type(chunk_path)
    if not mime_type:
        mime_type = "audio/x-m4a"
        
    groq_api_base = GROQ_API_BASE.rstrip('/')
    whisper_url = f"{groq_api_base}/openai/v1/audio/transcriptions"
    
    with open(chunk_path, "rb") as f:
        file_bytes = f.read()
        
    files = {
        "file": (os.path.basename(chunk_path), file_bytes, mime_type)
    }
    
    data = {
        "model": asr_model,
        "response_format": "verbose_json"
    }
    
    if language_mode in ["zh", "en"]:
        data["language"] = language_mode
        
    if language_mode == "zh":
        data["prompt"] = "这是一段中文录音，请在识别结果中加上适当的中文标点符号（如逗号、句号、问号、叹号等），确保句子结构完整通顺。"
    elif language_mode == "en":
        data["prompt"] = "This is an English audio recording. Please include appropriate punctuation marks (such as commas, periods, question marks, exclamation marks, etc.) in the transcription output."
        
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Connection": "close"
    }
    
    max_retries = 5
    response = None
    for attempt in range(max_retries):
        try:
            print(f"正在将分片 {os.path.basename(chunk_path)} 上传至 Groq Whisper... 尝试第 {attempt+1}/{max_retries} 次")
            async with get_httpx_client(timeout=150.0) as client:
                response = await client.post(
                    whisper_url,
                    files=files,
                    data=data,
                    headers=headers
                )
            if response.status_code == 200:
                break
            if response.status_code == 429:
                wait_time = 5.0 + attempt * 2.0
                print(f" -> 触发 ASR 限流 (429)，等待 {wait_time} 秒后重试...")
                await asyncio.sleep(wait_time)
            else:
                wait_time = 3.0 + attempt * 2.0
                print(f" -> ASR 响应异常 (HTTP {response.status_code}): {response.text}，等待 {wait_time} 秒后重试...")
                await asyncio.sleep(wait_time)
        except (httpx.HTTPError, Exception) as e:
            wait_time = 3.0 + attempt * 2.0
            print(f" -> ASR 网络请求异常 ({type(e).__name__}): {e}，等待 {wait_time} 秒后重试...")
            if attempt == max_retries - 1:
                raise e
            await asyncio.sleep(wait_time)
            
    if not response or response.status_code != 200:
        err_text = response.text if response else "未获取到响应"
        status_code = response.status_code if response else "Unknown"
        raise Exception(f"Groq Whisper 接口调用失败: {err_text} (HTTP {status_code})")
        
    whisper_result = response.json()
    return whisper_result.get("segments", [])

async def transcribe_audio_raw(filepath: str, language_mode: str, task_id: str = None, asr_model: str = "whisper-large-v3") -> list:
    """
    阶段 1: 调用 Groq Whisper API 进行语音识别，获取带有时间戳 and 标点 of 原始段落。
    支持自动切片（对于大于 24MB 的音频文件）。
    """
    if not GROQ_API_KEY:
        raise ValueError("未配置 GROQ_API_KEY，请检查服务端 .env 文件并完成配置。")
        
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"找不到需要转录的音频文件: {filepath}")
 
    # 初始化详细任务日志
    if task_id:
        from datetime import datetime
        try:
            os.makedirs("logs", exist_ok=True)
            log_file = os.path.join("logs", f"{task_id}.log")
            with open(log_file, "w", encoding="utf-8") as lf:
                lf.write(f"任务 ID: {task_id}\n")
                lf.write(f"音频文件路径: {filepath}\n")
                lf.write(f"语言模式: {language_mode}\n")
                lf.write(f"识别模型: {asr_model}\n")
                lf.write(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        except Exception as e:
            print(f"初始化任务日志失败: {e}")
            
    file_size = os.path.getsize(filepath)
    limit_size = 24 * 1024 * 1024  # 24MB
    
    raw_segments = []
    
    if file_size <= limit_size:
        print(f"音频文件大小为 {file_size / 1024 / 1024:.2f}MB，无需分片，直接上传转录。")
        raw_segments = await transcribe_single_chunk(filepath, language_mode, asr_model)
    else:
        print(f"音频文件大小为 {file_size / 1024 / 1024:.2f}MB，超过 24MB，进行 ffmpeg 自动分片转录...")
        temp_chunk_dir = os.path.join(os.path.dirname(filepath), f"chunks_{task_id or 'temp'}")
        os.makedirs(temp_chunk_dir, exist_ok=True)
        
        # 动态计算切片时间以保证约 15MB 一片，避免高码率超限或低码率切片过碎
        segment_time = 600
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", filepath,
                stdout=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            total_duration = float(stdout.decode().strip())
            if total_duration > 0:
                target_size = 15 * 1024 * 1024
                calc_time = int(total_duration * (target_size / file_size))
                segment_time = max(300, min(calc_time, 3600))  # 限制在 5分钟 ~ 60分钟 之间
                print(f"动态切片计算: 音频总长 {total_duration:.1f}s, 调整切片单位为 {segment_time} 秒 (预估 15MB/片)")
        except Exception as e:
            print(f"动态计算切片时长失败，回退到默认 600 秒: {e}")
            
        chunk_template = os.path.join(temp_chunk_dir, "chunk_%03d.m4a")
        
        cmd = [
            "ffmpeg", "-y",
            "-i", filepath,
            "-f", "segment",
            "-segment_time", str(segment_time),
            "-c", "copy",
            chunk_template
        ]
        
        try:
            print(f"执行 ffmpeg 分片命令: {' '.join(cmd)}")
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            try:
                await process.wait()
            except asyncio.CancelledError:
                print("ffmpeg 任务被取消，正在终止子进程...")
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                raise
            
            chunks = sorted([
                os.path.join(temp_chunk_dir, f)
                for f in os.listdir(temp_chunk_dir)
                if f.startswith("chunk_") and f.endswith(".m4a")
            ])
            
            if not chunks:
                raise Exception("ffmpeg 分片失败，未生成任何分片音频。")
                
            print(f"音频成功分割为 {len(chunks)} 个分片。")
            
            for idx, chunk_path in enumerate(chunks):
                offset = idx * segment_time
                print(f"正在处理第 {idx+1}/{len(chunks)} 个分片: {os.path.basename(chunk_path)} (时间偏移: {offset} 秒)...")
                
                chunk_segments = await transcribe_single_chunk(chunk_path, language_mode, asr_model)
                
                for seg in chunk_segments:
                    seg["start"] = round(seg.get("start", 0.0) + offset, 2)
                    seg["end"] = round(seg.get("end", 0.0) + offset, 2)
                    
                raw_segments.extend(chunk_segments)
                
            print("所有音频分片转录并合并成功。")
        finally:
            try:
                if os.path.exists(temp_chunk_dir):
                    shutil.rmtree(temp_chunk_dir)
                    print(f"分片临时目录已成功清理: {temp_chunk_dir}")
            except Exception as clean_ex:
                print(f"清理分片临时目录失败: {clean_ex}")
                
    if not raw_segments:
        raise Exception("Groq Whisper 未检测到任何语音或对话内容。")
        
    # 过滤 Whisper ASR 幻听词与噪音
    segments = filter_hallucinations(raw_segments)
    if not segments:
        raise Exception("语音识别结果在过滤幻听段落后变为空，请确认视频中是否包含有效的人声发言。")
        
    print(f"Groq Whisper 识别成功，共获取到 {len(segments)} 句带标点的原始句子。")
    
    # 将 Whisper ASR 原始文本段落写入日志
    if task_id:
        try:
            log_file = os.path.join("logs", f"{task_id}.log")
            with open(log_file, "a", encoding="utf-8") as lf:
                lf.write("========================================================================\n")
                lf.write(f"=== 阶段 1: 语音识别 (Whisper-large-v3) 原始句子 (共 {len(segments)} 句) ===\n")
                lf.write("========================================================================\n")
                for idx, seg in enumerate(segments):
                    start = seg.get("start", 0.0)
                    end = seg.get("end", 0.0)
                    text = seg.get("text", "")
                    lf.write(f"[{format_time(start)} - {format_time(end)}] (Seg ID: {idx}) {text}\n")
                lf.write("\n\n")
        except Exception as e:
            print(f"写入 ASR 原始日志失败: {e}")
            
    return segments

async def diarize_and_merge_segments(segments: list, task_id: str = None) -> list:
    """
    阶段 2: 调用 LongCat API 进行角色分离与智能句子合并（添加标点）。
    """
    if not LONGCAT_API_KEY:
        raise ValueError("未配置 LONGCAT_API_KEY，请检查服务端 .env 文件并完成配置。")
        
    longcat_api_base = LONGCAT_API_BASE.rstrip('/')
    longcat_url = f"{longcat_api_base}/openai/v1/chat/completions"
    longcat_headers = {
        "Authorization": f"Bearer {LONGCAT_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # 组装给大模型的原始输入段落，精简数据体积，防止超 Token 限制
    raw_inputs = []
    for seg in segments:
        raw_inputs.append({
            "start": round(seg.get("start", 0.0), 2),
            "end": round(seg.get("end", 0.0), 2),
            "text": seg.get("text", "")
        })
        
    ai_segments = []
    context_history = []
    global_last_segments = {}  # 全局追踪字典，保存每个 Speaker 目前为止的最后一句发言
    batch_size = 50
    chunks = [raw_inputs[i:i + batch_size] for i in range(0, len(raw_inputs), batch_size)]
    
    glossary_lines = []
    if CORRECTION_GLOSSARY:
        for k, v in CORRECTION_GLOSSARY.items():
            glossary_lines.append(f"     - 将“{k}”替换/纠正为“{v}”")
    glossary_str = "\n".join(glossary_lines) if glossary_lines else "     - 暂无"

    # 定义 System Prompt，包含合并规则、角色分类与克制纠错要求
    system_prompt = (
        "你是一个专业的对话剧本分析专家。你的任务是分析一段带有时间戳的语音识别草稿，根据上下文逻辑、谈话内容、问答关系等，区分不同的说话人角色，合并同一个人的连续发言，添加适当的标点符号，并整理成结构化的 JSON 剧本格式返回。\n\n"
        "你必须遵守以下极其严格的规则：\n"
        "1. 必须返回一个符合 JSON 规范的 JSON 对象，且根键为 \"segments\"，其值是一个数组。\n"
        "2. 数组中的每一个对象代表一句发言，必须包含以下四个字段：\n"
        "   - \"speaker\": 整数，代表发言人ID (如 0, 1, 2...)。\n"
        "   - \"start\": 浮点数，代表发言的开始时间。\n"
        "   - \"end\": 浮点数，代表发言的结束时间。\n"
        "   - \"text\": 字符串，代表发言的内容。\n"
        "3. **智能句子合并与标点纠错（极其重要）**：\n"
        "   - 当同一个说话人连续发言，且相邻句子之间没有长时间停顿（即前一句的 end 与后一句的 start 相差不超过 2.0 秒）且语义连贯时，你【必须】将它们合并为同一个段落。\n"
        "   - 合并时，你【必须】在拼接的文字间添加适当的标点符号（如逗号、句号、问号等），使段落通顺、符合语法排版。\n"
        "   - **智能错别字微调纠错**：在确保【绝对不改变句子原意、不删减关键句、不添加主观发挥内容、不进行重写润色】的大前提下，你【可以且应该】对输入文本中因为语音识别（ASR）局限导致的极明显同音/近音错别字、口误词（如“的地得”用错、“在/再”混淆、以及极明显的专有名词别字）进行克制、精准的替换纠正。除了这些极明显的别字纠错外，对于其余常规文字，必须保留所有的口头禅、口语重复词，严禁进行任何意义上的重写或改写。\n"
        f"   - **专有名词智能替换对照表**：对于以下特定的语音识别常见错词，你【必须】按对照表予以纠正替换：\n{glossary_str}\n"
        "   - 如果说话人切换，或者相邻句子的时间间隔大于 2.0 秒，则【绝对不能】合并，必须分成不同的发言段落，并各自添加末尾标点符号。\n"
        "4. 必须且只能包含输入中 `raw_segments` 部分的所有句子内容，绝对不允许遗漏或篡改。绝对不要在返回的 segments 中包含 `context_history` 里的任何句子！\n"
        "5. 不要输出任何除 JSON 之外的代码块、解释性文字或 Markdown 标签，必须直接返回合法的 JSON 字符串。\n\n"
        "【合并与标点补全示例】\n"
        "输入 `raw_segments`:\n"
        "[\n"
        "  {\"start\": 10.0, \"end\": 12.0, \"text\": \"我今年六十多\"},\n"
        "  {\"start\": 12.0, \"end\": 13.5, \"text\": \"退休好几年了\"},\n"
        "  {\"start\": 13.5, \"end\": 15.0, \"text\": \"我从三十几就开始\"},\n"
        "  {\"start\": 15.0, \"end\": 17.2, \"text\": \"为自己的后世\"},\n"
        "  {\"start\": 17.2, \"end\": 19.5, \"text\": \"看了很多死亡书\"},\n"
        "  {\"start\": 19.5, \"end\": 21.0, \"text\": \"这说明了什么呢\"},\n"
        "  {\"start\": 21.0, \"end\": 23.5, \"text\": \"就是你的意愿一定要说好\"},\n"
        "  {\"start\": 25.8, \"end\": 28.0, \"text\": \"如果不说好人家也不同意啊\"}\n"
        "]\n"
        "输出 JSON:\n"
        "{\n"
        "  \"segments\": [\n"
        "    {\n"
        "      \"speaker\": 0,\n"
        "      \"start\": 10.0,\n"
        "      \"end\": 19.5,\n"
        "      \"text\": \"我今年六十多，退休好几年了。我从三十几就开始，为自己的后世，看了很多死亡书。\"\n"
        "    },\n"
        "    {\n"
        "      \"speaker\": 0,\n"
        "      \"start\": 19.5,\n"
        "      \"end\": 23.5,\n"
        "      \"text\": \"这说明了什么呢？就是你的意愿一定要说好。\"\n"
        "    },\n"
        "    {\n"
        "      \"speaker\": 0,\n"
        "      \"start\": 25.8,\n"
        "      \"end\": 28.0,\n"
        "      \"text\": \"如果不说好人家也不同意啊。\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    
    print(f"正在通过 LongCat 进行语义说话人分类与句子合并，共 {len(chunks)} 个批次...")
    
    async def post_llama_with_retry(client, url, payload, headers, batch_label: str = "", max_retries=3):
        payload["stream"] = True
        for attempt in range(max_retries):
            try:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code == 429:
                        wait_time = 3.0
                        retry_after = resp.headers.get("Retry-After") or resp.headers.get("x-ratelimit-reset")
                        if retry_after:
                            try:
                                wait_time = float(retry_after)
                            except ValueError:
                                wait_time = 3.0
                        print(f" -> 触发 API 限流 (429)，等待 {wait_time} 秒后重试第 {attempt+1}/{max_retries} 次...")
                        await asyncio.sleep(wait_time)
                        continue
                    elif resp.status_code >= 500:
                        wait_time = 5.0
                        print(f" -> 触发服务端错误 ({resp.status_code})，等待 {wait_time} 秒后重试第 {attempt+1}/{max_retries} 次...")
                        await asyncio.sleep(wait_time)
                        continue
                        
                    if resp.status_code != 200:
                        error_text = await resp.aread()
                        class DummyResp:
                            def __init__(self, code, text):
                                self.status_code = code
                                self.text = text.decode("utf-8")
                            def json(self):
                                return {}
                        return DummyResp(resp.status_code, error_text)

                    first_token = True
                    full_content = ""
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                data_json = json.loads(data_str)
                                choices = data_json.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    if "content" in delta and delta["content"]:
                                        if first_token:
                                            print(f" -> {batch_label} 已开始接收流式响应数据...")
                                            first_token = False
                                        full_content += delta["content"]
                            except Exception:
                                pass
                                
                    class MockResponse:
                        def __init__(self, code, content):
                            self.status_code = code
                            self.text = content
                        def json(self):
                            return {"choices": [{"message": {"content": self.text}}]}
                            
                    return MockResponse(200, full_content)
                    
            except Exception as e:
                wait_time = 5.0
                print(f" -> 触发网络/连接错误 ({e.__class__.__name__}: {e})，等待 {wait_time} 秒后重试第 {attempt+1}/{max_retries} 次...")
                if attempt == max_retries - 1:
                    raise e
                await asyncio.sleep(wait_time)
                continue
        # 如果达到了 max_retries
        raise Exception("多次重试均失败")
 
    async with get_httpx_client(timeout=100.0, use_proxy=False) as client:
        for idx, chunk in enumerate(chunks):
            # 对单个批次加入重试循环，以应对大模型吐出损坏的 JSON
            for json_attempt in range(3):
                print(f" -> 正在请求大模型批次 {idx+1}/{len(chunks)} (当前批次原始句数: {len(chunk)}) [尝试 {json_attempt+1}/3]...")
                
                payload_data = {
                    "raw_segments": chunk
                }
                if context_history:
                    payload_data["context_history"] = context_history
                    
                user_prompt = (
                    "请将以下录音文本 raw_segments 进行多人发言角色分类并合并，并输出 JSON 数据。\n"
                    "如果提供了 context_history，它是上一段对话的结尾，仅供你作为上下文逻辑及说话人角色承接的参考。请在 raw_segments 的第一句中尽量承接 context_history 中的 speaker ID，使发言人编号保持连贯。但请记住：你返回的 JSON 'segments' 数组里【绝对不能】包含 context_history 中的任何句子！\n\n"
                    f"【需要你处理的数据】：\n{json.dumps(payload_data, ensure_ascii=False)}"
                )
                
                llama_payload = {
                    "model": "LongCat-2.0-Preview",
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.0,  # 0.0 以极力保证 JSON 语法结构的精准度和严格稳定性
                    "max_tokens": 120000  # 用户指定最大输出为 120k tokens
                }
                
                llama_response = await post_llama_with_retry(client, longcat_url, llama_payload, longcat_headers, batch_label=f"批次 {idx+1}/{len(chunks)}")
                
                if llama_response.status_code != 200:
                    raise Exception(f"LongCat 大模型请求失败: {llama_response.text} (HTTP {llama_response.status_code})")
                    
                llama_result = llama_response.json()
                content_str = llama_result["choices"][0]["message"]["content"]
                
                try:
                    structured_data = json.loads(content_str)
                    chunk_ai_segments = structured_data.get("segments", [])
                    
                    # 过滤可能被 Llama 意外混入的 context_history 句子
                    if chunk:
                        min_start = chunk[0]["start"]
                        chunk_ai_segments = [seg for seg in chunk_ai_segments if seg.get("start", 0.0) >= min_start - 0.01]
                        
                    ai_segments.extend(chunk_ai_segments)
                    
                    # 更新全局追踪字典：保存当前批次出现的每个说话人的最新一次发言。
                    # 质量过滤器：只有当新句长度 >= 8 字符，或者该说话人此前在字典中无记录时，才允许更新记录，防止碎句（如“对”、“好”）冲刷掉有特征的长句。
                    if chunk_ai_segments:
                        for seg in chunk_ai_segments:
                            sp = seg.get("speaker")
                            if sp is not None:
                                text = seg.get("text", "")
                                if sp not in global_last_segments or len(text) >= 8:
                                    global_last_segments[sp] = seg
                    
                    # 构造下一个批次的 context_history：获取全局所有出现过角色的最后发言，并按时间正序排列
                    if global_last_segments:
                        context_history = sorted(
                            list(global_last_segments.values()), 
                            key=lambda x: x.get("start", 0.0)
                        )
                    else:
                        context_history = []
                        
                    # 成功解析，跳出该批次的重试循环，进入下一个批次
                    break
                        
                except (KeyError, IndexError, json.JSONDecodeError) as e:
                    print(f" -> 批次 {idx+1} 解析 JSON 失败: {str(e)}")
                    if json_attempt == 2: # 已经是最后一次尝试
                        raise Exception(f"解析 LongCat 大模型 JSON 响应失败(已重试3次): {str(e)}。响应内容: {content_str[:300]}")
                    print(" -> 准备重新发起该批次请求...")
                    await asyncio.sleep(2.0)
        
    # ==========================================
    # 阶段三：转换数据格式，100% 对齐旧有系统
    # ==========================================
    formatted_results = []
    
    for seg in ai_segments:
        start_time = seg.get("start", 0.0)
        end_time = seg.get("end", 0.0)
        speaker_id = seg.get("speaker", 0)
        text = seg.get("text", "")
        
        # 兼容处理非整数 ID
        try:
            speaker_id = int(speaker_id)
        except Exception:
            speaker_id = 0
            
        formatted_results.append({
            "speaker": speaker_id,
            "start": start_time,
            "end": end_time,
            "time_str": f"[{format_time(start_time)} - {format_time(end_time)}]",
            "text": text.strip()
        })
        
    # 将 Llama 角色分离并合并后的文本句子写入日志
    if task_id:
        try:
            log_file = os.path.join("logs", f"{task_id}.log")
            with open(log_file, "a", encoding="utf-8") as lf:
                lf.write("========================================================================\n")
                lf.write(f"=== 阶段 2: 说话人识别与合并 (LongCat-2.0-Preview) 分析结果 (共 {len(formatted_results)} 句) ===\n")
                lf.write("========================================================================\n")
                for seg in formatted_results:
                    speaker = seg.get("speaker", 0)
                    time_str = seg.get("time_str", "")
                    text = seg.get("text", "")
                    lf.write(f"Speaker {speaker} {time_str} {text}\n")
                lf.write("\n\n")
        except Exception as e:
            print(f"写入 LLM 处理后日志失败: {e}")

    print(f"语意角色分离合并成功，已输出 {len(formatted_results)} 行带有说话人信息的剧本记录。")
    return formatted_results

async def transcribe_audio_file(filepath: str, language_mode: str, task_id: str = None, asr_model: str = "whisper-large-v3") -> list:
    """
    为了兼容旧有单入口设计，保留本函数，其内部顺序调用阶段 1 和阶段 2。
    """
    raw_segments = await transcribe_audio_raw(filepath, language_mode, task_id, asr_model)
    final_segments = await diarize_and_merge_segments(raw_segments, task_id)
    return final_segments
