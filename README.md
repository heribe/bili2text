# bili2text - 视频语音智能转录与多人剧本系统

bili2text 是一个轻量、美观且完全私有化部署的 B 站视频语音转录系统。它能抓取 B 站音频流，利用 SiliconFlow (TeleAI) 进行无幻觉的高精度语音识别，或直接提取 B 站官方 AI 字幕，再由大模型（LongCat）进行说话人识别和智能排版，最终产出高可读性的双轨剧本。

---

## ✨ 核心特性

- **双路并发提取**：支持同时提取 B 站官方 AI 字幕与云端高精语音识别（TeleAI）。官方字幕与云端 ASR 后台独立同步推进，支持单路抢先无缝出稿预览，随时平滑切换视图比对。
- **动态切片与智能省流**：自动识别并攫取极低码率省流音频。对于大型音频文件，利用 `ffprobe` 智能反算并动态切片（恒定维持在最优上传体积），以极致的网络传输效率完美突破 ASR API 的文件大小限制与并发压力。
- **大模型智能排版与纠错**：根据自定义词汇表自动进行精准的语法修正与全局说话人分离。内置 **SSE 流式通讯与 JSON 损坏自动重试机制**，确保处理海量长文本时不超时、不崩溃。
- **SSE 实时状态同步**：转录进度实时推送到前端，刷新页面或切换任务进度不丢失。
- **高级拟态 UI**：极简美观的毛玻璃风格界面，优化了数据源选择层级，支持移动端自适应。

---

## 📝 最近更新 (Changelog)

**2026-06-12 更新内容：**
- **底层架构**：彻底移除了易产生幻觉与碎语的 Groq Whisper，全线替换为更强大的 **SiliconFlow TeleAI** 模型，从根源上消除了长音频转录中的幻觉与重复乱码问题。
- **底层架构**：全面重构大模型 API 调用，接入 SSE 流式接收机制，彻底解决 Nginx 或 API 网关 504 超时问题。
- **稳定性**：修复了长音频 ffmpeg 动态切片时由于潜伏的 Python 缩进错误导致的转录跳过 Bug；将 TeleAI 的超时死等阈值提升至 300s，护航半小时级别的超大音频切片。
- **功能修复**：修复大模型代理连接问题（强制大模型直连避免被本地代理误杀）；修复网页端点“重试”时报告的 `update_task_status` 500 报错。
- **UI 改版**：重构新建任务的表单结构，将“双路并发”功能作为默认优先选项，并对色彩与卡片做了全新调整。
- **测试工具**：新增高精度自动化测试脚本 `tests/test_longcat_api.py`，支持 50 句长文本负载压测，自动统计模型思考耗时与生成速率。

---

## 🛠️ 安装与运行指南

### 1. 准备环境
- 安装 **FFmpeg** 并将其添加到系统 PATH 环境变量。
- **准备 B 站登录凭证（解决防爬封锁）**：
  在浏览器中使用 Cookie 导出插件（如 EditThisCookie），导出并保存以下两个文件至项目根目录：
  - **`cookies.txt`**（Netscape 格式，供后台免验证下载视频音频使用）
  - **`cookies.json`**（JSON 格式，**提取官方 AI 字幕必须配置**）

### 2. 初始化与安装
推荐使用官方极速包管理器 `uv`：
```bash
# 1. 创建并激活虚拟环境
uv venv
source .venv/bin/activate  # Windows 用户使用: .venv\Scripts\activate

# 2. 安装全部依赖
uv pip install fastapi uvicorn httpx yt-dlp python-dotenv requests bilibili-api-python
```

### 3. 配置密钥
```bash
cp .env.example .env
```
编辑 `.env` 文件，填入您的配置：
- `ACCESS_PASSWORD`：网页端的解锁密码
- `SILICONFLOW_API_KEY`：用于调用硅基流动 TeleAI 进行高清语音转录
- `LONGCAT_API_KEY`：用于调用 LongCat 大模型排版服务
- *（国内服务器如有需要，可配置 `HTTP_PROXY` 与 `HTTPS_PROXY`）*

### 4. 启动服务
```bash
uv run uvicorn main:app --port 8000 --host 0.0.0.0
```
启动后，浏览器访问 `http://127.0.0.1:8000` 即可解锁使用。

---

## 🌐 Linux 生产服务器部署 (Systemd)

在 Ubuntu/Debian 等系统上长期运行，推荐使用 Systemd 守护进程：

1. 创建服务配置：`sudo nano /etc/systemd/system/bili2text.service`
```ini
[Unit]
Description=bili2text API Daemon Service
After=network.target

[Service]
User=你的用户名
WorkingDirectory=/你的项目路径
Environment="PYTHONUNBUFFERED=1"
ExecStart=/你的项目路径/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
EnvironmentFile=/你的项目路径/.env

[Install]
WantedBy=multi-user.target
```

2. 启动服务与查看日志：
```bash
# 重新加载配置并设置开机自启
sudo systemctl daemon-reload
sudo systemctl enable bili2text

# 启动、停止与重启
sudo systemctl start bili2text
sudo systemctl stop bili2text
sudo systemctl restart bili2text

# 实时查看后台输出日志
sudo journalctl -u bili2text -f
```

### 推荐：Nginx 反向代理配置模版
当使用 Nginx 暴露外网或配置 HTTPS 时，请**务必针对 SSE 流式通讯关闭缓冲机制**，否则会导致前端进度条长时间卡顿甚至连接意外阻断。参考模版如下：

```nginx
server {
    listen 80;
    server_name your_domain.com;
    
    # 强制跳转 HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name your_domain.com;

    # 替换为你的 SSL 证书路径
    ssl_certificate /path/to/your/fullchain.pem;
    ssl_certificate_key /path/to/your/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 【极其重要】SSE 长连接进度通讯必备配置
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
        
        # 防止大文件转换过程中网关强制掐断连接
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
```

---

## 🔒 许可证
本项目基于 MIT 协议开源。
