import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# 读取配置
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "bili123")
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
LONGCAT_API_KEY = os.getenv("LONGCAT_API_KEY", "")

# 代理和中转配置
GROQ_API_BASE = os.getenv("GROQ_API_BASE", "https://api.groq.com")
LONGCAT_API_BASE = os.getenv("LONGCAT_API_BASE", "https://api.longcat.chat")
HTTP_PROXY = os.getenv("HTTP_PROXY", "")
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "")

# 数据库文件路径
DB_PATH = BASE_DIR / "bili2text.db"

# 临时音频文件存放文件夹
TEMP_DIR = BASE_DIR / "temp_audio"
TEMP_DIR.mkdir(exist_ok=True)

# 语音转录智能纠错词表（在第二阶段大模型合并排版时，将根据此表对 ASR 的常见错别字进行替换）
CORRECTION_GLOSSARY = {
    "毕站": "B站",
    "壁站": "B站",
    "哔哩哔哩": "B站",
    "避雷避雷": "哔哩哔哩",
    "避雷": "B站",
    "视频原": "视频源",
}
