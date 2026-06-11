import sqlite3
import json
from datetime import datetime
from config import DB_PATH
from contextlib import closing
import threading

db_lock = threading.Lock()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.row_factory = sqlite3.Row  # 允许通过列名访问数据
    return conn

def init_db():
    with db_lock:
        with closing(get_db_connection()) as conn:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        id TEXT PRIMARY KEY,
                        bili_url TEXT NOT NULL,
                        bvid TEXT UNIQUE NOT NULL,
                        title TEXT,
                        description TEXT,
                        language TEXT NOT NULL,
                        status TEXT NOT NULL,
                        error_msg TEXT,
                        result TEXT, -- 存储 JSON 格式的说话人剧本数据
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                try:
                    conn.execute("ALTER TABLE tasks ADD COLUMN raw_result TEXT")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE tasks ADD COLUMN asr_model TEXT")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE tasks ADD COLUMN transcribe_source TEXT DEFAULT 'whisper'")
                except sqlite3.OperationalError:
                    pass

def create_task(task_id: str, bili_url: str, bvid: str, language: str, asr_model: str = "whisper-large-v3", transcribe_source: str = "whisper"):
    now = datetime.now().isoformat()
    with db_lock:
        with closing(get_db_connection()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO tasks (id, bili_url, bvid, language, asr_model, transcribe_source, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (task_id, bili_url, bvid, language, asr_model, transcribe_source, "pending", now, now)
                )

def update_task_raw_result(task_id: str, source: str, raw_result_list: list):
    now = datetime.now().isoformat()
    with db_lock:
        with closing(get_db_connection()) as conn:
            with conn:
                row = conn.execute("SELECT raw_result FROM tasks WHERE id = ?", (task_id,)).fetchone()
                current_raw = {}
                if row and row['raw_result']:
                    try:
                        current_raw = json.loads(row['raw_result'])
                    except:
                        pass
                current_raw[source] = raw_result_list
                raw_result_str = json.dumps(current_raw, ensure_ascii=False)
                
                conn.execute(
                    "UPDATE tasks SET raw_result = ?, updated_at = ? WHERE id = ?",
                    (raw_result_str, now, task_id)
                )

def get_task(task_id: str):
    with db_lock:
        with closing(get_db_connection()) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row:
                return dict(row)
            return None

def get_task_by_bvid(bvid: str):
    with db_lock:
        with closing(get_db_connection()) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE bvid = ?", (bvid,)).fetchone()
            if row:
                return dict(row)
            return None

def get_all_tasks():
    with db_lock:
        with closing(get_db_connection()) as conn:
            rows = conn.execute("SELECT id, bili_url, bvid, title, language, status, created_at FROM tasks ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

def update_task_metadata(task_id: str, title: str, description: str):
    now = datetime.now().isoformat()
    with db_lock:
        with closing(get_db_connection()) as conn:
            with conn:
                conn.execute(
                    "UPDATE tasks SET title = ?, description = ?, updated_at = ? WHERE id = ?",
                    (title, description, now, task_id)
                )

def update_task_status(task_id: str, status: str, error_msg: str = None):
    now = datetime.now().isoformat()
    with db_lock:
        with closing(get_db_connection()) as conn:
            with conn:
                if error_msg is not None:
                    conn.execute(
                        "UPDATE tasks SET status = ?, error_msg = ?, updated_at = ? WHERE id = ?",
                        (status, error_msg, now, task_id)
                    )
                else:
                    conn.execute(
                        "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                        (status, now, task_id)
                    )

def update_task_result(task_id: str, source: str, result_list: list):
    now = datetime.now().isoformat()
    with db_lock:
        with closing(get_db_connection()) as conn:
            with conn:
                row = conn.execute("SELECT result FROM tasks WHERE id = ?", (task_id,)).fetchone()
                current_res = {}
                if row and row['result']:
                    try:
                        current_res = json.loads(row['result'])
                    except:
                        pass
                current_res[source] = result_list
                res_str = json.dumps(current_res, ensure_ascii=False)
                
                conn.execute(
                    "UPDATE tasks SET result = ?, updated_at = ? WHERE id = ?",
                    (res_str, now, task_id)
                )

def delete_task(task_id: str):
    with db_lock:
        with closing(get_db_connection()) as conn:
            with conn:
                conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

def reset_task(task_id: str):
    now = datetime.now().isoformat()
    with db_lock:
        with closing(get_db_connection()) as conn:
            with conn:
                conn.execute(
                    "UPDATE tasks SET status = 'pending', error_msg = NULL, raw_result = NULL, result = NULL, updated_at = ? WHERE id = ?",
                    (now, task_id)
                )
