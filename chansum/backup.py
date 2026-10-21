from __future__ import annotations

import hashlib
import contextlib
import json
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from .db import DB, SCHEMA, now
from .errors import WorkError
from .jobs import ACTIVE
from .deletion import cleanup as cleanup_deletions

TABLES = {'meta','items','lists','memberships','jobs','settings'}
MAX_BACKUP = 512 * 1024 * 1024


def idle(db: DB):
    if db.one("SELECT id FROM jobs WHERE status IN ('queued','collecting','summarizing','editing','rendering','interrupted') LIMIT 1"):
        raise WorkError('busy','처리 중인 작업을 완료하거나 취소한 뒤 백업·복원을 진행해 주세요.')


def create_backup(db: DB, destination: Path, worker=None):
    with db.maintenance:
        if worker and worker.current_item:
            raise WorkError('busy','작업 파일을 정리 중입니다. 작업이 끝난 뒤 백업해 주세요.')
        idle(db)
        with tempfile.TemporaryDirectory(prefix='chansum-backup-') as temporary:
            snapshot = Path(temporary)/'library.sqlite3'
            with db.connect() as connection, contextlib.closing(sqlite3.connect(snapshot)) as target:
                connection.backup(target)
            files = {'library.sqlite3':snapshot}
            for item in db.rows('SELECT id FROM items'):
                if not re.fullmatch('[0-9a-f]{32}',item['id']):
                    raise WorkError('unsafe_backup','자료 ID가 올바르지 않아 백업을 중단했습니다.')
                folder=db.root/'items'/item['id']
                for path in sorted(folder.rglob('*')):
                    if path.is_file() and path.suffix!='.tmp':
                        if path.is_symlink() or not path.resolve().is_relative_to(db.root.resolve()):
                            raise WorkError('unsafe_backup','데이터 폴더의 심볼릭 링크는 백업할 수 없습니다.')
                        files[path.relative_to(db.root).as_posix()] = path
            if sum(path.stat().st_size for path in files.values())>MAX_BACKUP:
                raise WorkError('too_large','현재 백업 크기 한도는 압축 전 512MB입니다.')
            manifest = {'format':'chansum','version':1,'created_at':now(),'files':{}}
            destination.parent.mkdir(parents=True,exist_ok=True)
            with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                for name,path in files.items():
                    # Hash the exact bytes written, never a separate earlier read.
                    content=path.read_bytes()
                    manifest['files'][name]=hashlib.sha256(content).hexdigest()
                    archive.writestr(name,content)
                archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))


def restore_backup(db: DB, archive_path: Path, worker=None) -> dict:
    with db.maintenance:
        if worker and worker.current_item:
            raise WorkError('busy','작업 파일을 정리 중입니다. 작업이 끝난 뒤 복원해 주세요.')
        idle(db)
        if cleanup_deletions(db):
            raise WorkError('busy','잠긴 파일의 삭제가 남아 있습니다. 파일을 사용하는 프로그램을 닫고 앱을 다시 실행해 주세요.')
        device_settings=db.settings()
        staging = Path(tempfile.mkdtemp(prefix='chansum-restore-',dir=db.root.parent))
        previous = db.root.parent/('chansum-before-restore-'+uuid.uuid4().hex[:10])
        try:
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    entries = archive.infolist()
                    if len(entries)>30000 or sum(i.file_size for i in entries)>MAX_BACKUP:
                        raise WorkError('too_large','백업은 압축 전 512MB·30,000개 파일 이하여야 합니다.')
                    names = [entry.filename for entry in entries]
                    if len(names)!=len(set(names)):
                        raise WorkError('invalid_backup','중복 경로가 있는 백업입니다.')
                    for entry in entries:
                        path = PurePosixPath(entry.filename)
                        if path.is_absolute() or '..' in path.parts or '\\' in entry.filename or ':' in entry.filename:
                            raise WorkError('invalid_backup','백업에 허용되지 않는 경로가 있습니다.')
                        if stat.S_ISLNK(entry.external_attr>>16) or entry.is_dir():
                            raise WorkError('invalid_backup','백업에 허용되지 않는 항목이 있습니다.')
                        if entry.filename not in ('manifest.json','library.sqlite3') and not entry.filename.startswith('items/'):
                            raise WorkError('invalid_backup','Chansum 데이터 외의 파일은 복원할 수 없습니다.')
                    manifest = json.loads(archive.read('manifest.json'))
                    if manifest.get('format')!='chansum' or manifest.get('version')!=1:
                        raise WorkError('invalid_backup','지원하지 않는 백업 형식입니다.')
                    if set(manifest['files']) != set(names)-{'manifest.json'}:
                        raise WorkError('invalid_backup','백업 파일 목록이 일치하지 않습니다.')
                    for name,digest in manifest['files'].items():
                        content = archive.read(name)
                        if hashlib.sha256(content).hexdigest()!=digest:
                            raise WorkError('invalid_backup','백업 파일의 무결성 검증에 실패했습니다.')
                        target = staging/name
                        target.parent.mkdir(parents=True,exist_ok=True)
                        target.write_bytes(content)
                snapshot = staging/'library.sqlite3'
                with sqlite3.connect(snapshot) as connection:
                    if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                        raise WorkError('invalid_backup','백업 DB 무결성 검사에 실패했습니다.')
                    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if tables!=TABLES or connection.execute("SELECT name FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():
                        raise WorkError('invalid_backup','백업 DB 구조가 올바르지 않습니다.')
                    with sqlite3.connect(':memory:') as reference:
                        reference.executescript(SCHEMA)
                        for table in TABLES:
                            expected=reference.execute('PRAGMA table_info('+table+')').fetchall()
                            actual=connection.execute('PRAGMA table_info('+table+')').fetchall()
                            if expected!=actual:
                                raise WorkError('invalid_backup','백업 DB 열 구조가 올바르지 않습니다.')
                    if connection.execute("SELECT value FROM meta WHERE key='version'").fetchone()!=('1',):
                        raise WorkError('invalid_backup','백업 DB 버전을 지원하지 않습니다.')
                    if connection.execute('PRAGMA foreign_key_check').fetchone():
                        raise WorkError('invalid_backup','백업 DB의 자료와 목록 연결이 손상되었습니다.')
                    for table in ('items','lists','jobs'):
                        if any(not isinstance(row[0],str) or not re.fullmatch('[0-9a-f]{32}',row[0]) for row in connection.execute('SELECT id FROM '+table)):
                            raise WorkError('invalid_backup','백업 DB의 자료·목록·작업 ID가 올바르지 않습니다.')
                    for source,result,thumbnail in connection.execute('SELECT source_path,result_path,thumbnail FROM items'):
                        for relative in (source,result,thumbnail):
                            if relative and not (staging/relative).resolve().is_relative_to(staging):
                                raise WorkError('invalid_backup','DB에 허용되지 않는 파일 경로가 있습니다.')
                        if source and not (staging/source).is_file():
                            raise WorkError('invalid_backup','백업에 보관된 원문 파일이 빠져 있습니다.')
                        if result and not (staging/result/'summary.json').is_file():
                            raise WorkError('invalid_backup','백업에 보관된 요약 파일이 빠져 있습니다.')
                    count = connection.execute('SELECT count(*) FROM items').fetchone()[0]
                    # Normal backups are idle. An imported unfinished job must
                    # never silently trigger a credentialed/paid request.
                    connection.execute("UPDATE items SET status='cancelled',active_job=NULL,error_code='restored_unfinished',error_message='백업의 미완료 작업입니다. AI 설정 확인 후 재시도해 주세요.' WHERE active_job IN (SELECT id FROM jobs WHERE status IN ('queued','collecting','summarizing','editing','rendering','interrupted'))")
                    connection.execute("UPDATE jobs SET status='cancelled',stage='cancelled',error_code='restored_unfinished',error_message='복원한 미완료 작업입니다. 설정 확인 후 재시도해 주세요.' WHERE status IN ('queued','collecting','summarizing','editing','rendering','interrupted')")
                    # Providers and credentials are configured on this machine.
                    # A library backup must not silently redirect future inputs.
                    connection.execute('DELETE FROM settings')
                    connection.executemany('INSERT INTO settings VALUES (?,?)',[(key,json.dumps(value)) for key,value in device_settings.items()])
                    connection.commit()
            except WorkError:
                raise
            except (zipfile.BadZipFile,KeyError,ValueError,sqlite3.Error,OSError):
                raise WorkError('invalid_backup','손상되었거나 올바르지 않은 Chansum 백업입니다.')
            # No live DB connections exist while the maintenance lock is held.
            db.root.rename(previous)
            try:
                staging.rename(db.root)
            except BaseException:
                previous.rename(db.root)
                raise
            return {'restored':count,'previous_data':str(previous),'message':'복원했습니다. 복원 전 데이터는 별도 폴더에 보존했습니다.'}
        finally:
            if staging.exists():
                shutil.rmtree(staging,ignore_errors=True)
