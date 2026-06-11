# bili2text - 视频语音智能转录与多人剧本系统

bili2text 是一个轻量、美观且完全私有化部署的 B 站视频语音转录系统。它能抓取 B 站音频流，利用 Whisper 进行高精度语音识别，或直接提取 B 站官方 AI 字幕，再由大模型（LongCat）进行说话人识别和智能排版，最终产出高可读性的双轨剧本。

---

## ✨ 核心特性

- **双路并发提取**：支持同时提取 B 站官方 AI 字幕与本地 Whisper 语音识别。官方字幕秒级出稿，Whisper 本地识别后台同步进行，支持随时切换比对。
- **大音频自动切片**：自动将大型音频无损切分并带时间偏置重组，完美突破 Whisper API 限制。
- **大模型智能排版与纠错**：根据自定义词汇表自动进行精准的语法修正与全局说话人分离。内置 **SSE 流式通讯与 JSON 损坏自动重试机制**，确保处理海量长文本时不超时、不崩溃。
- **SSE 实时状态同步**：转录进度实时推送到前端，刷新页面或切换任务进度不丢失。
- **高级拟态 UI**：极简美观的毛玻璃风格界面，优化了数据源选择层级，支持移动端自适应。

---

## 📝 最近更新 (Changelog)

**2026-06-11 更新内容：**
- **底层架构**：全面重构大模型 API 调用，接入 SSE 流式接收机制，彻底解决 Nginx 或 API 网关 504 超时问题。
- **稳定性**：新增大模型格式抽风（JSON 损坏）兜底策略，遇到乱码可自动等待并重发批次。
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
- `GROQ_API_KEY`：用于调用 Whisper ASR 服务
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
ExecStart=/你的项目路径/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
EnvironmentFile=/你的项目路径/.env

[Install]
WantedBy=multi-user.target
```

2. 启用并启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bili2text
```

*(推荐搭配 Nginx 反向代理配置 HTTPS。代理 SSE 请求时请务必配置 `proxy_buffering off;` 以防进度条卡顿或断连。)*

---

## 🔒 许可证
本项目基于 MIT 协议开源。
