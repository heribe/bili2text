import json

import database


def setup_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.init_db()
    return db_path


def test_create_and_fetch_task(monkeypatch, tmp_path):
    setup_temp_db(monkeypatch, tmp_path)

    database.create_task(
        "task-1",
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "BV1xx411c7mD",
        "zh",
        "TeleAI/TeleSpeechASR",
        "dual",
    )

    task = database.get_task("task-1")

    assert task["id"] == "task-1"
    assert task["bvid"] == "BV1xx411c7mD"
    assert task["language"] == "zh"
    assert task["asr_model"] == "TeleAI/TeleSpeechASR"
    assert task["transcribe_source"] == "dual"
    assert task["status"] == "pending"


def test_update_task_metadata_status_and_results(monkeypatch, tmp_path):
    setup_temp_db(monkeypatch, tmp_path)
    database.create_task("task-1", "url", "BV1xx411c7mD", "zh")

    database.update_task_metadata("task-1", "Title", "Description")
    database.update_task_status("task-1", "failed", error_msg="boom")
    database.update_task_raw_result("task-1", "whisper", [{"text": "raw"}])
    database.update_task_result("task-1", "whisper", [{"text": "final"}])

    task = database.get_task("task-1")

    assert task["title"] == "Title"
    assert task["description"] == "Description"
    assert task["status"] == "failed"
    assert task["error_msg"] == "boom"
    assert json.loads(task["raw_result"]) == {"whisper": [{"text": "raw"}]}
    assert json.loads(task["result"]) == {"whisper": [{"text": "final"}]}


def test_get_task_by_bvid_get_all_reset_and_delete(monkeypatch, tmp_path):
    setup_temp_db(monkeypatch, tmp_path)
    database.create_task("task-1", "url", "BV1xx411c7mD", "zh")
    database.update_task_status("task-1", "failed", error_msg="boom")
    database.update_task_raw_result("task-1", "whisper", [{"text": "raw"}])
    database.update_task_result("task-1", "whisper", [{"text": "final"}])

    assert database.get_task_by_bvid("BV1xx411c7mD")["id"] == "task-1"
    assert [task["id"] for task in database.get_all_tasks()] == ["task-1"]

    database.reset_task("task-1")
    reset_task = database.get_task("task-1")

    assert reset_task["status"] == "pending"
    assert reset_task["error_msg"] is None
    assert reset_task["raw_result"] is None
    assert reset_task["result"] is None

    database.delete_task("task-1")

    assert database.get_task("task-1") is None
