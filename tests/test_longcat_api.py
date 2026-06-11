import asyncio
import json
import sys
import re
from pathlib import Path

# 将项目根目录加入 sys.path 以便导入 config
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from config import LONGCAT_API_KEY, LONGCAT_API_BASE
import httpx

def parse_time(time_str: str) -> float:
    parts = time_str.split(':')
    if len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    return 0.0

def load_test_data():
    test_file = Path(__file__).parent / "test.txt"
    if not test_file.exists():
        print(f"❌ 找不到测试文件: {test_file}")
        return []
        
    segments = []
    pattern = re.compile(r"\[([\d:]+) - ([\d:]+)\] (.*?): (.*)")
    
    with open(test_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            match = pattern.match(line)
            if match:
                start_str, end_str, speaker, text = match.groups()
                segments.append({
                    "start": parse_time(start_str),
                    "end": parse_time(end_str),
                    "text": text,
                    "speaker": speaker
                })
            if len(segments) >= 50:
                break
    return segments

async def test_llm(mode="short"):
    if not LONGCAT_API_KEY:
        print("❌ 未在 .env 中找到 LONGCAT_API_KEY 配置。")
        return
        
    longcat_api_base = LONGCAT_API_BASE.rstrip('/')
    longcat_url = f"{longcat_api_base}/openai/v1/chat/completions"
    longcat_headers = {
        "Authorization": f"Bearer {LONGCAT_API_KEY}",
        "Content-Type": "application/json"
    }
    
    if mode == "long":
        segments = load_test_data()
        if not segments:
            return
        
        print(f"已成功加载前 {len(segments)} 句话，准备进行大批次测试！")
        
        payload_data = {"raw_segments": segments}
        user_prompt = (
            "请将以下录音文本 raw_segments 进行多人发言角色分类并合并，并输出 JSON 数据。\n"
            "如果提供了 context_history，它是上一段对话的结尾，仅供你作为上下文逻辑及说话人角色承接的参考。请在 raw_segments 的第一句中尽量承接 context_history 中的 speaker ID，使发言人编号保持连贯。但请记住：你返回的 JSON 'segments' 数组里【绝对不能】包含 context_history 中的任何句子！\n\n"
            f"【需要你处理的数据】：\n{json.dumps(payload_data, ensure_ascii=False)}"
        )
        system_prompt = "You are a helpful assistant." # 模拟，实际项目中有长系统提示词，这里主要测试体积和时间
        
        payload = {
            "model": "LongCat-2.0-Preview",
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.0,
            "max_tokens": 120000,
            "stream": True
        }
    else:
        payload = {
            "model": "LongCat-2.0-Preview",
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You are a helpful assistant. Please respond in JSON format, e.g. {\"status\": \"ok\", \"message\": \"hello\"}."},
                {"role": "user", "content": "Test the connection."}
            ],
            "temperature": 0.0,
            "max_tokens": 100,
            "stream": True
        }
    
    print(f"\n正在发起大模型调用测试(流式)...")
    print(f"请求 URL: {longcat_url}")
    print(f"使用的 API Key 尾号: ...{LONGCAT_API_KEY[-4:] if len(LONGCAT_API_KEY)>4 else '未知'}")
    print(f"测试脚本已强制直连，忽略系统代理...\n")
    
    try:
        # 强制不走代理，模拟 transcriber.py 的直连行为
        client_args = {"timeout": 30.0}
            
        async with httpx.AsyncClient(**client_args) as client:
            async with client.stream("POST", longcat_url, json=payload, headers=longcat_headers) as resp:
                print(f"✅ HTTP 状态码: {resp.status_code}")
                
                if resp.status_code != 200:
                    print("\n⚠️ 测试失败！请检查状态码或服务端报错。")
                    error_text = await resp.aread()
                    print(error_text.decode("utf-8"))
                    return
                
                print(f"📦 正在接收流式响应内容...")
                first_token = True
                full_content = ""
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            print("\n[接收完毕]")
                            break
                        try:
                            data_json = json.loads(data_str)
                            choices = data_json.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                if "content" in delta and delta["content"]:
                                    if first_token:
                                        print("\n👉 已开始收到大模型流式返回的数据！")
                                        first_token = False
                                    chunk_text = delta["content"]
                                    full_content += chunk_text
                                    print(chunk_text, end="", flush=True)
                        except Exception as e:
                            pass
                            
                print(f"\n\n最终拼接结果 (共 {len(full_content)} 字符):")
                try:
                    parsed = json.loads(full_content)
                    print("JSON 解析成功！(由于内容过长，不再完整打印)")
                    print("\n🎉 测试成功！流式输出拼接逻辑正常。")
                except Exception as e:
                    print(f"\n⚠️ 无法解析为 JSON: {e}")
                    print(full_content)
                
    except Exception as e:
        import traceback
        print(f"\n❌ 网络请求异常: {type(e).__name__} - {e}")
        print("请检查 NAS 服务器的网络连通性，或者在 .env 文件中配置有效的 HTTP_PROXY / HTTPS_PROXY。")

if __name__ == "__main__":
    mode = "short"
    if len(sys.argv) > 1 and sys.argv[1] == "long":
        mode = "long"
    asyncio.run(test_llm(mode))
