from __future__ import annotations

import json
import contextlib
import shutil
import threading
import uuid
from pathlib import Path

from . import collect
from .config import write_json
from .db import DB, now
from .engine import Engine, PROMPT_VERSION, cache_key, chunk_source, validate_summary
from .errors import Cancelled, WorkError
from .deletion import cleanup as cleanup_deletions
from .render import render_outputs
from .report import build_report

ACTIVE = ('queued','collecting','summarizing','editing','rendering','interrupted')


def enqueue(db: DB, item_id: str, options: dict, refresh=False, source_override: str | None = None, connection=None) -> str:
    job_id, timestamp = uuid.uuid4().hex, now()
    options = options | {'refresh_source':bool(refresh)}
    if source_override:
        source_file=db.path(source_override)
        if not source_file.is_relative_to((db.root/'items'/item_id).resolve()) or not source_file.is_file():
            raise WorkError('source_missing','재시도할 작업의 보관 원문을 찾을 수 없습니다. 원문 갱신을 선택해 주세요.')
    with (db.connect() if connection is None else contextlib.nullcontext(connection)) as connection:
        item = connection.execute('SELECT * FROM items WHERE id=? AND deleted_at IS NULL',(item_id,)).fetchone()
        if not item:
            raise WorkError('not_found','자료가 없거나 휴지통에 있습니다.')
        if item['active_job']:
            current = connection.execute('SELECT status FROM jobs WHERE id=?',(item['active_job'],)).fetchone()
            if current and current['status'] in ACTIVE:
                raise WorkError('busy','이미 처리 중인 자료입니다.')
        config = db.settings()
        if config['engine']=='ollama':
            # Bound source JSON and avoid Ollama's silently truncated default.
            config['chunk_chars']=min(config['chunk_chars'],4000)
            config['context_tokens']=32768
            config['output_tokens']=8192
        # An explicit model name is part of every cache key. For CLI defaults,
        # fingerprint the installed CLI/config model so changes invalidate caches.
        if config['engine']=='codex' and not config.get('model'):
            config['model_fingerprint'] = cli_fingerprint()
        connection.execute('INSERT INTO jobs(id,item_id,status,stage,options,engine,source_path,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                           (job_id,item_id,'queued','queued',json.dumps(options),json.dumps(config),
                            source_override or (None if refresh else item['source_path']),timestamp,timestamp))
        connection.execute('UPDATE items SET active_job=?,status=?,error_code=NULL,error_message=NULL,updated_at=? WHERE id=?',
                           (job_id,'queued',timestamp,item_id))
    return job_id


def cli_fingerprint() -> str:
    import hashlib
    import os
    import subprocess
    import tomllib
    from .config import codex_command, codex_arguments
    executable = codex_command()
    version = ''
    if executable:
        try:
            version = subprocess.run(codex_arguments('--version'),capture_output=True,text=True,timeout=8).stdout.strip()
        except Exception:
            pass
    config_path = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))/'config.toml'
    model_config = {}
    if config_path.is_file():
        try:
            config = tomllib.loads(config_path.read_text(encoding='utf-8'))
            model_config = {k:config.get(k) for k in ('model','model_provider','model_reasoning_effort')}
        except Exception:
            pass
    return hashlib.sha256(json.dumps([version,model_config],sort_keys=True).encode()).hexdigest()


class Worker:
    def __init__(self, db: DB, engine: Engine, local_base: str):
        self.db, self.engine, self.local_base = db, engine, local_base
        self.stop_event = threading.Event()
        self.wakeup = threading.Event()
        self.thread = None
        self.current_item = None

    def start(self):
        cleanup_deletions(self.db)
        with self.db.connect() as connection:
            connection.execute("UPDATE jobs SET status='interrupted',stage='interrupted',resume_count=resume_count+1,updated_at=? WHERE status IN ('collecting','summarizing','editing','rendering')",(now(),))
            connection.execute("UPDATE jobs SET status='cancelled',stage='cancelled' WHERE item_id IN (SELECT id FROM items WHERE deleted_at IS NOT NULL) AND status IN ('queued','interrupted')")
        self.thread = threading.Thread(target=self.loop,name='chansum-worker',daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wakeup.set()
        if self.thread:
            self.thread.join(timeout=3)

    def loop(self):
        while not self.stop_event.is_set():
            job = self.db.one("SELECT j.* FROM jobs j JOIN items i ON i.id=j.item_id WHERE j.status IN ('queued','interrupted') AND i.deleted_at IS NULL AND i.active_job=j.id ORDER BY j.created_at LIMIT 1")
            if job:
                self.current_item = job['item_id']
                try:
                    self.process(job)
                finally:
                    self.current_item = None
                    if not self.db.one('SELECT id FROM items WHERE id=?',(job['item_id'],)):
                        cleanup_deletions(self.db)
            else:
                self.wakeup.wait(1)
                self.wakeup.clear()

    def guard(self, job: dict):
        item = self.db.one('SELECT * FROM items WHERE id=?',(job['item_id'],))
        if self.stop_event.is_set() or not item or item['deleted_at'] or item['active_job']!=job['id']:
            raise Cancelled()
        current = self.db.one('SELECT status FROM jobs WHERE id=?',(job['id'],))
        if not current or current['status']=='cancelled':
            raise Cancelled()
        return item

    def progress(self, job: dict, stage: str, done: int, total: int):
        self.guard(job)
        with self.db.connect() as connection:
            connection.execute('UPDATE jobs SET status=?,stage=?,done=?,total=?,updated_at=? WHERE id=? AND status!=?',
                               (stage,stage,done,total,now(),job['id'],'cancelled'))
            connection.execute('UPDATE items SET status=?,updated_at=? WHERE id=? AND active_job=? AND deleted_at IS NULL',
                               (stage,now(),job['item_id'],job['id']))

    def process(self, job: dict):
        run = self.db.root/'items'/job['item_id']/'runs'/job['id']
        try:
            item = self.guard(job)
            config, options = json.loads(job['engine']), json.loads(job['options'])
            model_options={'mode':options.get('mode','brief')}
            run.mkdir(parents=True,exist_ok=True)
            self.progress(job,'collecting',0,1)
            if job['source_path'] and self.db.path(job['source_path']).exists():
                source = json.loads(self.db.path(job['source_path']).read_text(encoding='utf-8'))
            else:
                if item['kind']=='file':
                    files = list((self.db.root/'items'/item['id']/'input').glob('*'))
                    if not files:
                        raise WorkError('file_missing','원문 입력 파일이 없습니다. 파일을 다시 가져와 주세요.')
                    source = collect.from_file(files[0],files[0].name,item['url'])
                else:
                    source = collect.from_url(item['url'],config.get('youtube_fallback',True))
                self.guard(job)
                write_json(run/'source.json',source)
                (run/'source.txt').write_text('\n\n'.join(f'[{s["id"]}] {s["text"]}' for s in source['segments']),encoding='utf-8')
                job['source_path'] = str((run/'source.json').relative_to(self.db.root))
                with self.db.connect() as connection:
                    connection.execute('UPDATE jobs SET source_path=? WHERE id=?',(job['source_path'],job['id']))
                    connection.execute('UPDATE items SET source_path=COALESCE(source_path,?) WHERE id=? AND active_job=? AND deleted_at IS NULL',
                                       (job['source_path'],item['id'],job['id']))
                    # Preserve user-edited titles on regeneration.
                    if not item['result_path'] and (item['title']==item['url'] or item['title'].startswith('YouTube ·')):
                        connection.execute('UPDATE items SET title=? WHERE id=? AND active_job=? AND deleted_at IS NULL',
                                           (source['title'],item['id'],job['id']))
                self.thumbnail(item,source)
            chunks = chunk_source(source,config['chunk_chars'])
            results, failures = [], []
            state, hits = json.loads(job['chunks']), job['cache_hits']
            for index,segments in enumerate(chunks):
                self.progress(job,'summarizing',index+1,len(chunks)+2)
                key = cache_key(source,segments,config,model_options)
                cached = self.db.root/'cache'/f'{key}.json'
                try:
                    summary = None
                    if cached.exists():
                        try:
                            summary = validate_summary(json.loads(cached.read_text(encoding='utf-8')),{s['id'] for s in segments})
                            hits += 1
                        except (WorkError,ValueError,OSError):
                            cached.unlink(missing_ok=True)
                    if summary is None:
                        summary = validate_summary(self.engine.summarize(segments,options,config,self.db.root/'work'),{s['id'] for s in segments})
                        self.guard(job)
                        write_json(cached,summary)
                    state[str(index)] = {'status':'complete','cache_key':key,'segment_ids':[s['id'] for s in segments]}
                    results.append(summary)
                except WorkError as error:
                    state[str(index)] = {'status':'failed','error_code':error.code,'error_message':error.message,
                                         'segment_ids':[s['id'] for s in segments]}
                    failures.append(error)
                self.guard(job)
                self.db.execute('UPDATE jobs SET chunks=?,cache_hits=?,done=?,updated_at=? WHERE id=?',
                                (json.dumps(state,ensure_ascii=False),hits,index+2,now(),job['id']))
                if failures and failures[-1].code in ('ai_auth','engine_missing','ai_permission','ai_rate_limited','ai_network'):
                    # A global prerequisite failure will affect every chunk; don't
                    # make repeated paid/authentication requests.
                    break
            if not results:
                raise failures[0] if failures else WorkError('empty_summary','완료된 요약 구간이 없습니다.')
            failed_count = len(chunks)-len(results)
            report,report_hits=build_report(results,source,self.engine,config,model_options|{'partial':bool(failed_count)},
                                           self.db.root/'cache',run,lambda *args:self.progress(job,*args),lambda:self.guard(job))
            self.db.execute('UPDATE jobs SET cache_hits=? WHERE id=?',(hits+report_hits,job['id']))
            summary = {'title':report['title'],'message':report['message']|{'kind':'argument'},
                       'layout':report['visual']['kind'],'report':report,
                       'sections':[section for result in results for section in result['sections']],
                       'partial':bool(failed_count),'failed_chunks':failed_count,'chunk_count':len(chunks),
                       'processed_chunks':len(results),'prompt_version':PROMPT_VERSION,
                       'engine':'test-double' if getattr(self.engine,'is_test_double',False) else config['engine'],
                       'model':'extractive-fixture' if getattr(self.engine,'is_test_double',False) else config.get('model') or 'Codex CLI 기본값',
                       'model_fingerprint':config.get('model_fingerprint'),
                       'source_hash':source['hash'],'options':options,
                       'verification':'test-double' if getattr(self.engine,'is_test_double',False) else 'live-engine',
                       'missing_segments':sorted({s['id'] for i,c in enumerate(chunks) if state.get(str(i),{}).get('status')!='complete' for s in c})}
            self.progress(job,'rendering',0,1)
            self.db.execute('UPDATE jobs SET result_path=? WHERE id=?',(str(run.relative_to(self.db.root)),job['id']))
            render_outputs(run,job['item_id'],summary,source,self.local_base)
            self.guard(job)
            status = 'partial' if failed_count else 'complete'
            error_message = f'{failed_count}개 분할 구간을 처리하지 못했습니다. 검증된 구간만 저장했습니다.' if failed_count else None
            with self.db.connect() as connection:
                connection.execute('UPDATE jobs SET status=?,stage=?,done=total,error_code=?,error_message=?,updated_at=? WHERE id=? AND status!=?',
                                   (status,status,'partial_chunks' if failed_count else None,error_message,now(),job['id'],'cancelled'))
                connection.execute('UPDATE items SET result_path=?,source_path=?,status=?,error_code=?,error_message=?,updated_at=? WHERE id=? AND active_job=? AND deleted_at IS NULL',
                                   (str(run.relative_to(self.db.root)),job['source_path'],status,
                                    'partial_chunks' if failed_count else None,error_message,now(),job['item_id'],job['id']))
        except Cancelled:
            self.db.execute("UPDATE jobs SET status=?,stage=?,updated_at=? WHERE id=? AND status IN ('queued','collecting','summarizing','editing','rendering','interrupted')",
                            ('interrupted' if self.stop_event.is_set() else 'cancelled',
                             'interrupted' if self.stop_event.is_set() else 'cancelled',now(),job['id']))
        except WorkError as error:
            self.fail(job,error,run)
        except Exception:
            self.fail(job,WorkError('internal','처리 중 오류가 발생했습니다. 원문과 기존 성공 결과는 보존됩니다. 재시도하거나 파일 입력을 사용해 주세요.'),run)

    def fail(self, job: dict, error: WorkError, run: Path):
        with self.db.connect() as connection:
            connection.execute("UPDATE jobs SET status='failed',stage='failed',error_code=?,error_message=?,updated_at=? WHERE id=? AND status!='cancelled'",
                               (error.code,error.message,now(),job['id']))
            connection.execute("UPDATE items SET status='failed',error_code=?,error_message=?,updated_at=? WHERE id=? AND active_job=? AND deleted_at IS NULL",
                               (error.code,error.message,now(),job['item_id'],job['id']))

    def thumbnail(self,item: dict,source: dict):
        if not source.get('thumbnail_url') or item.get('thumbnail'):
            return
        try:
            raw,_,mime = collect.fetch_url(source['thumbnail_url'],2*1024*1024)
            if mime.split(';')[0] not in ('image/jpeg','image/png','image/webp'):
                return
            extension = {'image/jpeg':'jpg','image/png':'png','image/webp':'webp'}[mime.split(';')[0]]
            path = self.db.root/'items'/item['id']/('thumbnail.'+extension)
            path.write_bytes(raw)
            self.db.execute('UPDATE items SET thumbnail=? WHERE id=? AND deleted_at IS NULL',
                            (str(path.relative_to(self.db.root)),item['id']))
        except Exception:
            pass
