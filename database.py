import sqlite3
import json
from datetime import datetime
from config import DB_PATH

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 允许通过列名访问数据
    return conn

def init_db():
    with get_db_connection() as conn:
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
        conn.commit()

def create_task(task_id: str, bili_url: str, bvid: str, language: str, asr_model: str = "whisper-large-v3"):
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO tasks (id, bili_url, bvid, language, asr_model, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, bili_url, bvid, language, asr_model, "pending", now, now)
        )
        conn.commit()

def update_task_raw_result(task_id: str, raw_result_dict: list):
    now = datetime.now().isoformat()
    raw_result_str = json.dumps(raw_result_dict) if raw_result_dict is not None else None
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE tasks SET raw_result = ?, updated_at = ? WHERE id = ?",
            (raw_result_str, now, task_id)
        )
        conn.commit()

def get_task(task_id: str):
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row:
            return dict(row)
        return None

def get_task_by_bvid(bvid: str):
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE bvid = ?", (bvid,)).fetchone()
        if row:
            return dict(row)
        return None

def get_all_tasks():
    with get_db_connection() as conn:
        rows = conn.execute("SELECT id, bili_url, bvid, title, language, status, created_at FROM tasks ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

def update_task_metadata(task_id: str, title: str, description: str):
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE tasks SET title = ?, description = ?, updated_at = ? WHERE id = ?",
            (title, description, now, task_id)
        )
        conn.commit()

def update_task_status(task_id: str, status: str, error_msg: str = None, result_dict: list = None):
    now = datetime.now().isoformat()
    result_str = json.dumps(result_dict) if result_dict is not None else None
    with get_db_connection() as conn:
        if error_msg is not None:
            conn.execute(
                "UPDATE tasks SET status = ?, error_msg = ?, updated_at = ? WHERE id = ?",
                (status, error_msg, now, task_id)
            )
        elif result_str is not None:
            conn.execute(
                "UPDATE tasks SET status = ?, result = ?, updated_at = ? WHERE id = ?",
                (status, result_str, now, task_id)
            )
        else:
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, task_id)
            )
        conn.commit()

def delete_task(task_id: str):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()

def reset_task(task_id: str):
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE tasks SET status = 'pending', error_msg = NULL, raw_result = NULL, result = NULL, updated_at = ? WHERE id = ?",
            (now, task_id)
        )
        conn.commit()
