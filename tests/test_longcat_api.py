import asyncio
import json
import sys
from pathlib import Path

# 将项目根目录加入 sys.path 以便导入 config
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from config import LONGCAT_API_KEY, LONGCAT_API_BASE, HTTP_PROXY, HTTPS_PROXY
import httpx

async def test_llm():
    if not LONGCAT_API_KEY:
        print("❌ 未在 .env 中找到 LONGCAT_API_KEY 配置。")
        return
        
    longcat_api_base = LONGCAT_API_BASE.rstrip('/')
    longcat_url = f"{longcat_api_base}/openai/v1/chat/completions"
    longcat_headers = {
        "Authorization": f"Bearer {LONGCAT_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "LongCat-2.0-Preview",
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. Please respond in JSON format, e.g. {\"status\": \"ok\", \"message\": \"hello\"}."},
            {"role": "user", "content": "Test the connection."}
        ],
        "temperature": 0.0,
        "max_tokens": 100
    }
    
    payload["stream"] = True
    print(f"正在发起大模型调用测试(流式)...")
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
                                    chunk_text = delta["content"]
                                    full_content += chunk_text
                                    print(chunk_text, end="", flush=True)
                        except Exception as e:
                            pass
                            
                print(f"\n\n最终拼接结果:")
                try:
                    parsed = json.loads(full_content)
                    print(json.dumps(parsed, indent=2, ensure_ascii=False))
                    print("\n🎉 测试成功！流式输出拼接逻辑正常。")
                except Exception as e:
                    print(f"\n⚠️ 无法解析为 JSON: {e}")
                    print(full_content)
                
    except Exception as e:
        import traceback
        print(f"\n❌ 网络请求异常: {type(e).__name__} - {e}")
        print("请检查 NAS 服务器的网络连通性，或者在 .env 文件中配置有效的 HTTP_PROXY / HTTPS_PROXY。")

if __name__ == "__main__":
    asyncio.run(test_llm())
