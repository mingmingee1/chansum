from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .config import DEFAULT_SETTINGS


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO meta VALUES ('version','1');
CREATE TABLE IF NOT EXISTS items(
 id TEXT PRIMARY KEY, identity TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
 kind TEXT NOT NULL, url TEXT, thumbnail TEXT, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, deleted_at TEXT, favorite INTEGER NOT NULL DEFAULT 0,
 note TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'queued',
 source_path TEXT, result_path TEXT, active_job TEXT, error_code TEXT, error_message TEXT
);
CREATE TABLE IF NOT EXISTS lists(id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memberships(
 item_id TEXT REFERENCES items(id) ON DELETE CASCADE,
 list_id TEXT REFERENCES lists(id) ON DELETE CASCADE,
 PRIMARY KEY(item_id,list_id)
);
CREATE TABLE IF NOT EXISTS jobs(
 id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
 status TEXT NOT NULL, stage TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
 total INTEGER NOT NULL DEFAULT 1, options TEXT NOT NULL, engine TEXT NOT NULL,
 source_path TEXT, result_path TEXT, chunks TEXT NOT NULL DEFAULT '{}',
 error_code TEXT, error_message TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 resume_count INTEGER NOT NULL DEFAULT 0, cache_hits INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status,created_at);
CREATE INDEX IF NOT EXISTS items_deleted ON items(deleted_at,created_at);
"""


class DB:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.database_file = root / "library.sqlite3"
        self.maintenance = threading.RLock()
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextlib.contextmanager
    def connect(self):
        with self.maintenance:
            db = sqlite3.connect(self.database_file, timeout=30)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=30000")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def rows(self, sql: str, args=()) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args)]

    def one(self, sql: str, args=()) -> dict | None:
        rows = self.rows(sql, args)
        return rows[0] if rows else None

    def execute(self, sql: str, args=()):
        with self.connect() as db:
            return db.execute(sql, args).rowcount

    def settings(self) -> dict:
        return DEFAULT_SETTINGS | {r['key']: json.loads(r['value']) for r in self.rows('SELECT * FROM settings')}

    def save_settings(self, settings: dict):
        with self.connect() as db:
            for key, value in settings.items():
                if key in DEFAULT_SETTINGS:
                    db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key,json.dumps(value)))

    def item(self, item_id: str, deleted=True) -> dict | None:
        item = self.one('SELECT * FROM items WHERE id=?' + ('' if deleted else ' AND deleted_at IS NULL'), (item_id,))
        if item:
            item['lists'] = self.rows('SELECT l.* FROM lists l JOIN memberships m ON l.id=m.list_id WHERE m.item_id=? ORDER BY l.name', (item_id,))
            item['favorite'] = bool(item['favorite'])
            item['has_result'] = bool(item['result_path'])
        return item

    def path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError('허용되지 않는 파일 경로입니다.')
        return path
