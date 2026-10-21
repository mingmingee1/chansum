"""Durable, narrowly scoped cleanup for explicitly confirmed permanent deletes."""
import json
import re
import shutil

from .config import write_json
from .errors import WorkError


def pending(db):
    with db.maintenance:
        path=db.root/'pending-deletions.json'
        try:values=json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:values=[]
        if not isinstance(values,list) or any(not isinstance(value,str) or not re.fullmatch('[0-9a-f]{32}',value) for value in values):
            raise WorkError('deletion_journal','삭제 예약 기록이 손상되었습니다. 데이터 폴더를 보존한 뒤 복구해 주세요.')
        return values


def mark(db,ids):
    with db.maintenance:
        values=sorted(set(pending(db))|set(ids))
        try:write_json(db.root/'pending-deletions.json',values)
        except OSError:raise WorkError('storage_error','삭제 예약을 저장하지 못했습니다. 데이터 폴더 권한과 용량을 확인해 주세요.')


def cleanup(db):
    with db.maintenance:
        remaining=[]
        for identifier in pending(db):
            # If the SQL transaction never committed, or a backup restored this
            # ID, its live data must be preserved.
            if db.one('SELECT id FROM items WHERE id=?',(identifier,)):
                continue
            folder=db.root/'items'/identifier
            if folder.resolve().is_relative_to(db.root.resolve()):
                shutil.rmtree(folder,ignore_errors=True)
            if folder.exists():remaining.append(identifier)
        path=db.root/'pending-deletions.json'
        if remaining:write_json(path,remaining)
        else:path.unlink(missing_ok=True)
        return len(remaining)
