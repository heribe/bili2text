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
    
    proxy_url = HTTPS_PROXY or HTTP_PROXY
    print(f"正在发起大模型调用测试...")
    print(f"请求 URL: {longcat_url}")
    print(f"使用的 API Key 尾号: ...{LONGCAT_API_KEY[-4:] if len(LONGCAT_API_KEY)>4 else '未知'}")
    if proxy_url:
        print(f"使用的代理配置: {proxy_url}\n")
    else:
        print(f"未配置代理，正在直连...\n")
    
    try:
        # 使用和 transcriber.py 一致的代理加载逻辑
        client_args = {"timeout": 30.0}
        if proxy_url:
            client_args["proxy"] = proxy_url
            
        async with httpx.AsyncClient(**client_args) as client:
            resp = await client.post(longcat_url, json=payload, headers=longcat_headers)
            print(f"✅ HTTP 状态码: {resp.status_code}")
            print(f"📦 响应内容:")
            
            try:
                # 尝试格式化 JSON 输出以便于阅读
                parsed = resp.json()
                print(json.dumps(parsed, indent=2, ensure_ascii=False))
            except Exception:
                print(resp.text)
                
            if resp.status_code == 200:
                print("\n🎉 测试成功！大模型接口通信正常。")
            else:
                print("\n⚠️ 测试失败！请检查状态码或服务端报错。")
                
    except Exception as e:
        import traceback
        print(f"\n❌ 网络请求异常: {type(e).__name__} - {e}")
        print("请检查 NAS 服务器的网络连通性，或者在 .env 文件中配置有效的 HTTP_PROXY / HTTPS_PROXY。")

if __name__ == "__main__":
    asyncio.run(test_llm())
