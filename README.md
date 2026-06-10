# bili2text - 视频语音智能转录与多人剧本系统

bili2text 是一个轻量、美观、高内聚且完全私有化部署的 Bilibili 视频语音转录与智能多人对话剧本整理系统。

系统能够自动抓取 B 站视频的音频流，利用 Groq 高性能 Whisper 端点进行高精度语音识别，并依托大模型（LongCat）进行说话人识别（Diarization）和智能句子合并排版，最终产出带有时间戳、高可读性的双轨剧本。

---

## ✨ 核心特性

- **三阶段解耦流水线队列**：将“视频分析下载”、“语音识别（ASR）”、“大模型排版（LLM）”拆分为独立队列，各阶段具备最高并发（2）限制，支持任务删除时后台线程秒级强行 cancel 协程并无痕清理垃圾。
- **大音频 FFmpeg 自动切片**：自动检测超过 24MB 的大型音频文件，利用 FFmpeg 在微秒级内无损切分为 10 分钟片段分批进行 ASR 识别，带时间偏置自动重组，完美突破 Groq 25MB 物理限制并极大提升代理环境下的上传成功率。
- **全局说话人 ID 追踪器**：使用全局状态追踪字典继承历史说话人信息，解决多人对话中由于某个角色跨大段沉默而在后续批次中被错判为新角色的难题。
- **发言特征质量过滤器**：只有当句子字数 $\ge 8$ 时才允许更新说话人最新发言记录，避免“对”、“好”、“嗯”等无特征碎句冲刷抹除掉有特征的长句，维持大模型人设判定一致性。
- **专有名词与同音字智能纠错**：支持在 `config.py` 中自定义专有名词词汇表（Glossary），在保留 100% 原始 ASR 草稿的前提下，在第二阶段大模型整理时对“的地得/在再”及 B站 专属词（如“毕站”纠正为“B站”）执行极其精准、克制的语法修复。
- **SSE 实时状态同步 & 强刷恢复**：后端 SSE 发送端缓存了正在运行中任务的最新一条进度消息。无论是刷新页面还是点击切换历史纪录，前端页面能瞬间从 0% 同步为最真实的当前进度（如 65% 或 85%），彻底告别僵死或闪烁 10% 的问题。
- **防断联 HTTP 下载降级**：移除了代理强制直连限制以兼容代理网络，为 `yt-dlp` 开启了忽略 SSL 校验和强制降级 HTTP 连接的高级指令，免去任何 `[SSL: UNEXPECTED_EOF_WHILE_READING]` 的断联烦恼。
- **高级磨砂玻璃拟态 UI**：完全采用现代 CSS HSL 设计与毛玻璃微动效，具备极强的视觉冲击力与美感；自适应手机端，支持剧本一键复制与后台详细运行日志直接追溯。

---

## 🛠️ 技术栈

- **后端**：Python 3.12+ / FastAPI / Uvicorn / SQLite
- **依赖与包管理**：`uv` (超快速 Python 包管理器)
- **底层工具**：FFmpeg (纯音频无损切片) / yt-dlp (免证书 B 站视频解析)
- **接口服务**：Groq ASR API (Whisper-large-v3 / Turbo) / LongCat API (LongCat-2.0-Preview)
- **前端**：原生 HTML5 / Vanilla CSS (现代 Glassmorphism) / Native JavaScript (SSE 监听 & 事件驱动)

---

## 📁 项目结构说明

```text
E:\Code\bili2text\
├── main.py              # FastAPI 路由入口、生命周期启动器与 SSE 端点
├── queue_worker.py      # 三阶段（下载/ASR/LLM）并发工作者队列协程
├── transcriber.py       # ASR 上传、FFmpeg 切片逻辑、大模型全局追踪合并与纠错 Prompt
├── downloader.py        # B站 视频元数据抓取与 HTTP 媒体流无证书下载
├── database.py          # SQLite 本地任务、状态、草稿、结果落库管理
├── progress.py          # SSE 实时进度缓存订阅中心
├── config.py            # 本地解锁密码、API KEY 以及纠错词汇表的配置文件
├── static/              # 前端静态资源
│   ├── index.html       # 磨砂玻璃质感 UI 主页面
│   ├── style.css        # 精致的 CSS 设计样式表
│   └── app.js           # 带有长连接复原和状态追踪的前端控制脚本
├── .env.example         # 环境变量配置模板
└── .gitignore           # 忽略 .venv, .env, *.db, 临时文件夹等
```

---

## ⚙️ 配置文件定义

### 1. 密钥与访问配置 (`.env`)
在项目根目录下复制一份模板：
```bash
cp .env.example .env
```
并填入您的具体密钥：
```ini
# 解锁主工作台的访问密码（默认为 bili123）
ACCESS_PASSWORD=bili123

# Groq Cloud API Key（申请地址：https://console.groq.com/）
GROQ_API_KEY=gsk_your_groq_api_key_here

# LongCat API Key（申请地址：https://api.longcat.chat/）
LONGCAT_API_KEY=your_longcat_api_key_here

# [选填] 网络代理配置（如果服务器在国内无法直接请求 Groq/LongCat，可配置代理）
# HTTP_PROXY=http://127.0.0.1:7890
# HTTPS_PROXY=http://127.0.0.1:7890

# [选填] API 接口中转域名（如果使用中转服务，在此修改端点）
# GROQ_API_BASE=https://api.groq.com
# LONGCAT_API_BASE=https://api.longcat.chat
```


### 2. 语音智能纠错映射词库
您可以随时在 `config.py` 中的 `CORRECTION_GLOSSARY` 字典中添加您经常在视频中遇到被 Whisper 识别错误的特定专有名词：
```python
CORRECTION_GLOSSARY = {
    "毕站": "B站",
    "壁站": "B站",
    "哔哩哔哩": "B站",
    "避雷": "B站",
    "避雷避雷": "哔哩哔哩",
    "视频原": "视频源",
    # 您可以继续在这里往下添加 ...
}
```

---

## 💻 本地运行指南

### 1. 安装 FFmpeg
确保您的操作系统中已安装并配置了 `ffmpeg` 和 `ffprobe`（且需要存在于系统环境变量中）：
* **Windows**：推荐从 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 下载 `full_build`，并将其 `bin` 路径添加到系统 PATH 环境变量。
* **MacOS**：`brew install ffmpeg`
* **Linux (Ubuntu/Debian)**：`sudo apt update && sudo apt install -y ffmpeg`

### 2. 初始化环境并安装依赖
我们强烈推荐使用官方速度飞快的 `uv` 工具完成环境依赖部署：
```bash
# 1. 确保在 bili2text 根目录，初始化虚拟环境
uv venv

# 2. 激活虚拟环境
# Windows:
.venv\Scripts\activate
# Linux/MacOS:
source .venv/bin/activate

# 3. 安装依赖包
uv pip install fastapi uvicorn httpx yt-dlp python-dotenv
```

### 3. 本地启动
```bash
uv run uvicorn main:app --port 8000 --host 127.0.0.1
```
打开浏览器访问：`http://127.0.0.1:8000` 即可解锁工作台使用。

---

## 🌐 Linux 服务器生产部署指南

在生产服务器上，推荐使用 `Systemd` 管理服务以实现开机自启、奔溃自动拉起和后台守护进程管理。以下是 Ubuntu/Debian 系统的完整步骤：

### 1. 服务器安装系统依赖
```bash
# 1. 更新包管理器并安装 FFmpeg
sudo apt update
sudo apt install -y ffmpeg git

# 2. 全局安装 uv (速度比普通 pip ... 依赖管理器快 10-100 倍的 Python 包管理器)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

### 2. 克隆项目并初始化
```bash
# 1. 克隆代码至目标路径（如 /var/www/bili2text）
cd /var/www
sudo git clone https://github.com/yourusername/bili2text.git
sudo chown -R $USER:$USER /var/www/bili2text
cd bili2text

# 2. 用 uv 创建专属虚拟环境并一键安装依赖
uv venv
uv pip install fastapi uvicorn httpx yt-dlp python-dotenv

# 3. 配置生产环境变量
cp .env.example .env
nano .env  # 填入您真实的 API_KEY 并修改您的解锁密码
```

### 3. 注册 Systemd 守护进程服务
创建 Systemd 服务配置文件：
```bash
sudo nano /etc/systemd/system/bili2text.service
```
将以下配置粘贴进去，注意将 `User` 和 `WorkingDirectory` 修改为您真实的用户名与路径：
```ini
[Unit]
Description=bili2text API Daemon Service
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/var/www/bili2text
# 指向我们刚刚用 uv 建立在虚拟环境中的 uvicorn
ExecStart=/var/www/bili2text/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
# 导入 .env 环境密钥
EnvironmentFile=/var/www/bili2text/.env

[Install]
WantedBy=multi-user.target
```

### 4. 启动与管理服务
```bash
# 1. 重新加载系统守护进程配置文件
sudo systemctl daemon-reload

# 2. 启用开机自启服务
sudo systemctl enable bili2text

# 3. 启动 bili2text 核心服务
sudo systemctl start bili2text

# 4. 查看当前服务运行状态（应显示绿色 Active: active (running)）
sudo systemctl status bili2text
```

### 5. 运维常用指令
* **查看实时日志**：`sudo journalctl -u bili2text -f`
* **重启后台服务**：`sudo systemctl restart bili2text`
* **停止服务**：`sudo systemctl stop bili2text`

### 6. Nginx 反向代理与 HTTPS 配置 (可选但推荐)
为了将服务暴露至公网并在 80/443 端口提供安全的 SSL 支持，推荐挂载 Nginx：

安装 Nginx：
```bash
sudo apt install -y nginx
```
创建 Nginx 虚拟主机配置：
```bash
sudo nano /etc/nginx/sites-available/bili2text
```
写入配置：
```nginx
server {
    listen 80;
    server_name yourdomain.com; # 填入您的域名或公网IP

    # 代理 SSE (Server-Sent Events) 的长连接必须加上这几行以防止被 Nginx 强制断连或缓冲
    location /api/tasks/ {
        proxy_pass http://127.0.0.1:8000/api/tasks/;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Host $http_host;
        
        # 禁用 Nginx 缓冲，对 SSE 实时推送极为重要
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # 通用 HTTP 请求代理
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}
```
激活配置并重启 Nginx：
```bash
sudo ln -s /etc/nginx/sites-available/bili2text /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```
如需配置 SSL (HTTPS)，推荐直接使用 Certbot 自动化部署：
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

---

## ❓ 常见问题：如何解决 B 站下载 HTTP 412 错误 / 滑块人机验证

如果在 Linux 服务器（尤其是腾讯云、阿里云等云服务商机房公网 IP）上运行转录下载时，后台报错 `HTTP Error 412: Precondition Failed`。这是因为 B 站对云机房未登录状态下的网页请求执行了严格的反爬封锁策略。

**终极解决方案：**
1. 在您个人电脑的浏览器中打开并登录您的 Bilibili 账号。
2. 在浏览器中安装 Cookies 导出扩展（例如 Chrome/Edge 商店中的 `Get cookies.txt` 或 `Get cookies.txt LOCALLY`）。
3. 使用扩展导出 B 站域名的 Cookies，保存为名为 **`cookies.txt`** 的文本文件。
4. 将此 `cookies.txt` 文件上传并放置到您服务器上项目的根目录下（即与 `main.py` 和 `config.py` 在同一级路径）。
5. **bili2text 会在下载时自动检测并无缝加载此 `cookies.txt`**。由于请求带上了您账号真实的登录态（Cookies），B 站网关将直接放行，彻底消除 412 及滑块人机校验限制！

---

## 🔒 许可证

本项目基于 MIT 协议开源。
