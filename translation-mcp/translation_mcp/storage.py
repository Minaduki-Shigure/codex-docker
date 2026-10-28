import json
import os
import sqlite3
from pathlib import Path


class RequestConflict(Exception):
    pass


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, digest TEXT NOT NULL, status TEXT NOT NULL, result TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        self.db.commit()

    def claim(self, request_id: str, digest: str):
        cursor = self.db.execute("INSERT OR IGNORE INTO requests(id,digest,status) VALUES(?,?, 'running')", (request_id, digest))
        self.db.commit()
        if cursor.rowcount:
            return None
        old_digest, status, result = self.db.execute("SELECT digest,status,result FROM requests WHERE id=?", (request_id,)).fetchone()
        if old_digest != digest:
            raise RequestConflict("request_id_reused_with_different_input")
        if status == "running":
            raise RequestConflict("request_in_progress_or_interrupted_check_before_retry")
        return json.loads(result)

    def finish(self, request_id: str, result: dict):
        self.db.execute("UPDATE requests SET status='finished',result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), request_id))
        self.db.commit()

    def close(self):
        self.db.close()
