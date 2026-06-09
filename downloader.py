import re
import os
import asyncio
import httpx
import yt_dlp
from pathlib import Path
from config import TEMP_DIR

def extract_bvid(url_or_bvid: str) -> str:
    """
    提取 URL 或输入字符串中的 BVID
    """
    url_or_bvid = url_or_bvid.strip()
    # 匹配 B 站 BV 号的正则表达式 (BV 开头加 10 位 Base58 字符)
    match = re.search(r'(BV[a-zA-Z0-9]{10})', url_or_bvid, re.IGNORECASE)
    if match:
        return match.group(1)
    raise ValueError("未检测到有效的 Bilibili BV 号或链接，请检查输入")

async def get_video_metadata_api(bvid: str) -> dict:
    """
    通过 B 站官方网页端 API 获取视频标题与描述（最快、最稳定）
    """
    url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/"
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers=headers)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("code") == 0:
                data = res_json.get("data", {})
                return {
                    "title": data.get("title", "未命名视频"),
                    "description": data.get("desc", "无简介")
                }
    raise Exception("Bilibili API 请求失败")

async def get_video_metadata_ytdlp(bvid: str) -> dict:
    """
    作为备选方案，使用 yt-dlp 提取视频元数据
    """
    url = f"https://www.bilibili.com/video/{bvid}"
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'noplaylist': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.bilibili.com/',
        }
    }
    
    def run_extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "title": info.get("title", "未命名视频"),
                "description": info.get("description", "无简介")
            }
            
    return await asyncio.to_thread(run_extract)

async def get_video_metadata(bvid: str) -> dict:
    """
    综合获取元数据，包含降级容错机制
    """
    try:
        return await get_video_metadata_api(bvid)
    except Exception:
        # 降级到 yt-dlp 提取
        try:
            return await get_video_metadata_ytdlp(bvid)
        except Exception as e:
            raise Exception(f"解析视频元数据失败: {str(e)}")

async def download_audio(bvid: str, progress_callback) -> str:
    """
    下载 B 站视频的纯音频轨，保存为临时的 .m4a 格式
    progress_callback 接受 0-100 的整数，表示下载进度
    """
    url = f"https://www.bilibili.com/video/{bvid}"
    # yt-dlp 下载模板，保存到临时目录
    # 注意用 bvid 作为文件名，避免重名冲突
    output_template = str(TEMP_DIR / f"{bvid}.%(ext)s")
    
    def ydl_progress_hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes') or 0
            if total > 0:
                percent = int(downloaded / total * 100)
                # 回传进度
                progress_callback(percent)
        elif d['status'] == 'finished':
            progress_callback(100)

    ydl_opts = {
        'format': 'bestaudio/best',  # 提取最高画质纯音频
        'outtmpl': output_template,
        'noplaylist': True,
        'quiet': True,
        'progress_hooks': [ydl_progress_hook],
        'retries': 10,  # 网络波动时增加重试次数
        'fragment_retries': 10,
        'nocheckcertificate': True,  # 禁用证书校验，解决代理软件伪造/解密带来的 SSL EOF 错误
        'extractor_args': {
            'bilibili': {
                'prefer_http': True  # 强制 B 站媒体流走 HTTP 而不是 HTTPS，彻底绕开 SSL 协议断开限制
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.bilibili.com/',
            'Origin': 'https://www.bilibili.com',
        }
    }

    def run_download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # 获取实际保存的扩展名
            ext = info.get('ext', 'm4a')
            filepath = TEMP_DIR / f"{bvid}.{ext}"
            return str(filepath)

    return await asyncio.to_thread(run_download)

def delete_temp_file(filepath: str):
    """
    销毁下载的临时文件，确保无痕管理
    """
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
            print(f"临时音频文件已销毁: {filepath}")
    except Exception as e:
        print(f"销毁临时音频文件失败 {filepath}: {e}")
