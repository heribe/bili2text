import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# 读取配置
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "bili123")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
LONGCAT_API_KEY = os.getenv("LONGCAT_API_KEY", "")

# 数据库文件路径
DB_PATH = BASE_DIR / "bilivoice.db"

# 临时音频文件存放文件夹
TEMP_DIR = BASE_DIR / "temp_audio"
TEMP_DIR.mkdir(exist_ok=True)
