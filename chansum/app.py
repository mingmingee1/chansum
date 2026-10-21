from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from . import __version__
from .backup import MAX_BACKUP, create_backup, restore_backup
from .collect import MAX_SOURCE, normalize_url
from .config import ASSETS, ROOT, Secrets, codex_command, codex_arguments, config_root, data_root
from .db import DB, now
from .engine import Engine
from .errors import WorkError
from .jobs import ACTIVE, Worker, enqueue
from .deletion import mark as mark_deletions, cleanup as cleanup_deletions, pending as pending_deletions


class AddURLs(BaseModel):
    urls: list[str] = Field(min_length=1,max_length=30)
    mode: str = Field(default='detail',pattern='^(brief|detail)$')
    list_ids: list[str] = Field(default_factory=list,max_length=100)


class PatchItem(BaseModel):
    title: str | None = Field(default=None,min_length=1,max_length=250)
    note: str | None = Field(default=None,max_length=30000)
    favorite: bool | None = None


class JobOptions(BaseModel):
    mode: str = Field(default='detail',pattern='^(brief|detail)$')
    refresh: bool = False


class ListName(BaseModel):
    name: str = Field(min_length=1,max_length=60)


class Bulk(BaseModel):
    ids: list[str] = Field(min_length=1,max_length=500)
    action: str = Field(pattern='^(trash|restore|purge|favorite|lists_add|lists_remove)$')
    list_ids: list[str] = Field(default_factory=list,max_length=100)
    confirm: str = ''


class EngineSettings(BaseModel):
    engine: str = Field(pattern='^(codex|openai|ollama)$')
    model: str = Field(default='',max_length=120,pattern=r'^[A-Za-z0-9._:/@+-]*$')
    base_url: str = Field(default='https://api.openai.com/v1',max_length=300)
    chunk_chars: int = Field(default=12000,ge=1000,le=40000)
    timeout: int = Field(default=180,ge=20,le=600)
    youtube_fallback: bool = True
    api_key: str | None = Field(default=None,max_length=2000)
    clear_api_key: bool = False


def create_app(data_dir: Path | None = None, private_dir: Path | None = None, engine: Engine | None = None, start_worker=True) -> FastAPI:
    data_location = (data_dir or data_root()).resolve()
    private_location = (private_dir or config_root()).resolve()
    if private_location.is_relative_to(data_location) or data_location.is_relative_to(private_location):
        raise WorkError('unsafe_config','데이터 폴더와 비밀키 설정 폴더는 서로 겹치지 않는 별도 위치여야 합니다.')
    database = DB(data_location)
    secret_store = Secrets(private_location)
    ai = engine or Engine(secret_store)
    port = int(os.environ.get('CHANSUM_PORT','9417'))
    worker = Worker(database,ai,f'http://127.0.0.1:{port}')
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            worker.start()
        yield
        worker.stop()

    app = FastAPI(title='Chansum',version=__version__,lifespan=lifespan,docs_url=None,redoc_url=None)
    app.state.db, app.state.worker, app.state.engine = database, worker, ai
    app.state.token = token

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        host = request.headers.get('host','').split(':')[0].lower()
        if host not in ('127.0.0.1','localhost','testserver'):
            return JSONResponse({'detail':'로컬 주소에서만 사용할 수 있습니다.'},status_code=403)
        if request.method not in ('GET','HEAD','OPTIONS'):
            if request.headers.get('x-chansum-token') != token:
                return JSONResponse({'detail':'페이지를 새로고침한 뒤 다시 시도해 주세요.'},status_code=403)
            origin = request.headers.get('origin')
            if origin and origin != f'{request.url.scheme}://{request.headers.get("host")}':
                return JSONResponse({'detail':'다른 사이트의 요청은 허용하지 않습니다.'},status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        ancestors = "'self'" if request.url.path.endswith('/preview/pdf') else "'none'"
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data:; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors "+ancestors+"; form-action 'self'"
        if request.url.path.startswith('/api'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(WorkError)
    async def work_error(request,error):
        status = 404 if error.code=='not_found' else 409 if error.code=='busy' else 400
        return JSONResponse({'detail':error.message,'code':error.code},status_code=status)

    def get_item(item_id: str, deleted=False):
        item = database.item(item_id,deleted)
        if not item:
            raise WorkError('not_found','자료가 없거나 휴지통에 있습니다.')
        return item

    def check_lists(list_ids):
        for list_id in list_ids:
            if not database.one('SELECT id FROM lists WHERE id=?',(list_id,)):
                raise WorkError('list_missing','선택한 목록이 없습니다. 목록을 다시 선택해 주세요.')

    def add_item(*args,**kwargs):
        with database.maintenance:
            return insert_item(*args,**kwargs)

    def insert_item(identity, title, kind, url, mode, lists, input_file=None):
        existing = database.one('SELECT id,deleted_at,title FROM items WHERE identity=?',(identity,))
        if existing:
            return {'duplicate':True,'id':existing['id'],'title':existing['title'],'in_trash':bool(existing['deleted_at'])}
        item_id, timestamp = uuid.uuid4().hex, now()
        try:
            with database.connect() as connection:
                connection.execute('INSERT INTO items(id,identity,title,kind,url,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                                   (item_id,identity,title,kind,url,timestamp,timestamp))
                for list_id in lists:
                    connection.execute('INSERT OR IGNORE INTO memberships VALUES (?,?)',(item_id,list_id))
                if input_file:
                    filename, content = input_file
                    target = database.root/'items'/item_id/'input'/filename
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(content)
                job_id = enqueue(database,item_id,{'mode':mode},connection=connection)
        except BaseException as error:
            if not database.one('SELECT id FROM items WHERE id=?',(item_id,)):
                shutil.rmtree(database.root/'items'/item_id,ignore_errors=True)
            if isinstance(error,OSError):
                raise WorkError('storage_error','원문을 저장하지 못했습니다. 데이터 폴더 권한과 용량을 확인해 주세요.')
            raise
        worker.wakeup.set()
        return {'duplicate':False,'id':item_id,'title':title,'job_id':job_id}

    @app.get('/',response_class=HTMLResponse)
    def index():
        return (ROOT/'chansum/static/index.html').read_text(encoding='utf-8').replace('{{CSRF_TOKEN}}',token)

    @app.get('/api/health')
    def health():
        return {'app':'chansum','version':__version__,'data_dir':str(database.root),'test_mode':bool(getattr(ai,'is_test_double',False))}

    @app.get('/api/session')
    def session():
        return {'token':token}

    @app.get('/api/items')
    def items(q: str = '', sort: str = 'latest', kind: str = '', list_id: str = '', trash: bool = False, favorite: bool = False):
        where, params = ['i.deleted_at IS NOT NULL' if trash else 'i.deleted_at IS NULL'], []
        if q:
            pattern = '%'+q.replace('!','!!').replace('%','!%').replace('_','!_')+'%'
            where.append("(i.title LIKE ? ESCAPE '!' OR i.note LIKE ? ESCAPE '!' OR i.url LIKE ? ESCAPE '!')")
            params.extend([pattern]*3)
        if kind:
            where.append('i.kind=?'); params.append(kind)
        if list_id:
            where.append('EXISTS(SELECT 1 FROM memberships m WHERE m.item_id=i.id AND m.list_id=?)'); params.append(list_id)
        if favorite:
            where.append('i.favorite=1')
        order = 'i.title COLLATE NOCASE ASC' if sort=='title' else 'i.created_at DESC'
        rows = database.rows('SELECT i.* FROM items i WHERE '+' AND '.join(where)+' ORDER BY '+order,params)
        for item in rows:
            item['has_result'] = bool(item['result_path'])
            item['lists'] = database.rows('SELECT l.id,l.name FROM lists l JOIN memberships m ON m.list_id=l.id WHERE m.item_id=? ORDER BY l.name',(item['id'],))
        return {'items':rows,'total':len(rows)}

    @app.post('/api/items/urls')
    def add_urls(body: AddURLs):
        check_lists(body.list_ids)
        results, rejected = [], []
        for raw in body.urls:
            try:
                url,kind,_ = normalize_url(raw)
                results.append(add_item('url:'+url,url,kind,url,body.mode,body.list_ids))
            except WorkError as error:
                rejected.append({'input':raw[:300],'code':error.code,'message':error.message})
        return {'results':results,'rejected':rejected}

    @app.post('/api/items/files')
    async def add_files(files: list[UploadFile] = File(...), mode: str = Form('detail'), list_ids: str = Form('[]')):
        if mode not in ('brief','detail') or len(files)>20:
            raise WorkError('invalid_input','한 번에 파일 20개까지 가져올 수 있습니다.')
        try:
            lists = json.loads(list_ids)
            if not isinstance(lists,list) or not all(isinstance(s,str) for s in lists):
                raise ValueError()
        except ValueError:
            raise WorkError('invalid_input','목록 선택 정보가 올바르지 않습니다.')
        check_lists(lists)
        results, rejected = [], []
        for upload in files:
            name = PureWindowsPath(upload.filename or 'input.txt').name
            name = re.sub(r'[\x00-\x1f<>:"/\\|?*]','_',name)[:160]
            extension = Path(name).suffix.lower()
            if extension not in ('.txt','.srt','.vtt','.html','.htm'):
                rejected.append({'input':name,'message':'TXT·SRT·VTT·HTML 파일을 선택해 주세요.'}); continue
            buffer = bytearray()
            while part := await upload.read(1024*1024):
                buffer.extend(part)
                if len(buffer)>MAX_SOURCE:
                    break
            await upload.close()
            if len(buffer)>MAX_SOURCE:
                rejected.append({'input':name,'message':'파일당 최대 12MB입니다.'}); continue
            identity = 'file:'+hashlib.sha256(buffer).hexdigest()
            # Disk/SQLite work belongs off the ASGI event loop.
            try:
                result = await asyncio.to_thread(add_item,identity,Path(name).stem,'file',None,mode,lists,(name,buffer))
                results.append(result)
            except WorkError as error:
                rejected.append({'input':name,'code':error.code,'message':error.message})
        return {'results':results,'rejected':rejected}

    @app.post('/api/items/bulk')
    def bulk(body: Bulk):
        check_lists(body.list_ids)
        selected = [get_item(item_id,deleted=True) for item_id in set(body.ids)]
        if body.action=='purge':
            if body.confirm!='DELETE' or any(not item['deleted_at'] for item in selected):
                raise WorkError('confirmation','휴지통에 있는 자료만 삭제 범위를 확인한 뒤 영구 삭제할 수 있습니다.')
        timestamp = now()
        with database.connect() as connection:
            if body.action=='purge':mark_deletions(database,[item['id'] for item in selected])
            for item in selected:
                item_id = item['id']
                if body.action=='trash':
                    connection.execute("UPDATE jobs SET status='cancelled',stage='cancelled',updated_at=? WHERE item_id=? AND status IN ('queued','collecting','summarizing','editing','rendering','interrupted')",(timestamp,item_id))
                    connection.execute("UPDATE items SET deleted_at=?,active_job=NULL,status=CASE WHEN status IN ('queued','collecting','summarizing','editing','rendering','interrupted') THEN 'cancelled' ELSE status END,updated_at=? WHERE id=?",(timestamp,timestamp,item_id))
                elif body.action=='restore':
                    connection.execute('UPDATE items SET deleted_at=NULL,updated_at=? WHERE id=?',(timestamp,item_id))
                elif body.action=='purge':
                    connection.execute('DELETE FROM items WHERE id=?',(item_id,))
                elif body.action=='favorite':
                    connection.execute('UPDATE items SET favorite=1,updated_at=? WHERE id=?',(timestamp,item_id))
                else:
                    for list_id in body.list_ids:
                        if body.action=='lists_add':
                            connection.execute('INSERT OR IGNORE INTO memberships VALUES (?,?)',(item_id,list_id))
                        else:
                            connection.execute('DELETE FROM memberships WHERE item_id=? AND list_id=?',(item_id,list_id))
        if body.action=='purge':
            remaining=cleanup_deletions(database)
            return {'updated':len(selected),'pending_cleanup':remaining}
        return {'updated':len(selected),'pending_cleanup':0}

    @app.get('/api/items/{item_id}')
    def detail(item_id: str):
        item = get_item(item_id)
        source, result = None, None
        if item['source_path'] and database.path(item['source_path']).exists():
            source = json.loads(database.path(item['source_path']).read_text(encoding='utf-8'))
        if item['result_path']:
            path = database.path(item['result_path'])/'summary.json'
            if path.exists():
                result = json.loads(path.read_text(encoding='utf-8'))
        jobs = database.rows('SELECT * FROM jobs WHERE item_id=? ORDER BY created_at DESC',(item_id,))
        for job in jobs:
            job['options'] = json.loads(job['options'])
            job['chunks'] = json.loads(job['chunks'])
            job['engine'] = json.loads(job['engine'])
        downloads = [name for name,file in {'png':'infographic.png','pdf':'report.pdf','svg':'infographic.svg','html':'report.html','json':'summary.json'}.items()
                     if item['result_path'] and (database.path(item['result_path'])/file).exists()]
        return {'item':item,'source':source,'summary':result,'jobs':jobs,'downloads':downloads}

    @app.patch('/api/items/{item_id}')
    def edit(item_id: str, body: PatchItem):
        get_item(item_id)
        values = body.model_dump(exclude_none=True)
        if values:
            if 'title' in values:
                values['title'] = values['title'].strip()
                if not values['title']:
                    raise WorkError('invalid_input','제목은 비워둘 수 없습니다.')
            statement = ','.join(f'{key}=?' for key in values)
            database.execute(f'UPDATE items SET {statement},updated_at=? WHERE id=?',(*values.values(),now(),item_id))
        return database.item(item_id)

    @app.post('/api/items/{item_id}/regenerate')
    def regenerate(item_id: str, body: JobOptions):
        get_item(item_id)
        job = enqueue(database,item_id,{'mode':body.mode},body.refresh)
        worker.wakeup.set()
        return {'job_id':job}

    @app.get('/api/items/{item_id}/download/{format}')
    def download(item_id: str, format: str):
        item = get_item(item_id)
        formats = {'png':('infographic.png','image/png'),'pdf':('report.pdf','application/pdf'),
                   'svg':('infographic.svg','image/svg+xml'),'html':('report.html','text/plain'),
                   'json':('summary.json','application/json'),'source':('source.txt','text/plain')}
        if format not in formats:
            raise WorkError('not_found','지원하지 않는 다운로드 형식입니다.')
        filename,mime = formats[format]
        if format=='source':
            if not item['source_path']:
                raise WorkError('not_found','수집된 원문이 없습니다.')
            path = database.path(item['source_path']).with_name('source.txt')
        else:
            path = database.path(item['result_path'])/filename if item['result_path'] else None
        if not path or not path.exists():
            raise WorkError('not_found','아직 생성되지 않은 파일입니다.')
        safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',item['title'])[:80]
        return FileResponse(path,media_type=mime,filename=safe_title+'.'+filename.split('.')[-1])

    @app.get('/api/items/{item_id}/preview/pdf')
    def preview(item_id: str):
        item = get_item(item_id)
        path = database.path(item['result_path'])/'report.pdf' if item['result_path'] else None
        if not path or not path.exists():
            raise WorkError('not_found','PDF가 아직 생성되지 않았습니다.')
        return FileResponse(path,media_type='application/pdf',headers={'Content-Disposition':'inline'})

    @app.get('/api/items/{item_id}/thumbnail')
    def thumbnail(item_id: str):
        item = get_item(item_id)
        if not item['thumbnail'] or not database.path(item['thumbnail']).exists():
            raise WorkError('not_found','확보된 썸네일이 없습니다.')
        return FileResponse(database.path(item['thumbnail']))

    @app.get('/api/jobs')
    def jobs():
        return {'jobs':database.rows('SELECT j.id,j.item_id,j.status,j.stage,j.done,j.total,j.error_code,j.error_message,j.created_at,j.updated_at,j.resume_count,j.cache_hits,i.title,i.deleted_at FROM jobs j JOIN items i ON j.item_id=i.id ORDER BY j.created_at DESC LIMIT 300')}

    @app.post('/api/jobs/{job_id}/retry')
    def retry(job_id: str):
        job = database.one('SELECT * FROM jobs WHERE id=?',(job_id,))
        if not job:
            raise WorkError('not_found','작업을 찾을 수 없습니다.')
        get_item(job['item_id'])
        options=json.loads(job['options'])
        new = enqueue(database,job['item_id'],options,options.get('refresh_source',False),job['source_path'])
        worker.wakeup.set()
        return {'job_id':new}

    @app.post('/api/jobs/{job_id}/cancel')
    def cancel(job_id: str):
        job = database.one('SELECT * FROM jobs WHERE id=?',(job_id,))
        if not job:
            raise WorkError('not_found','작업을 찾을 수 없습니다.')
        database.execute("UPDATE jobs SET status='cancelled',stage='cancelled',updated_at=? WHERE id=? AND status IN ('queued','collecting','summarizing','editing','rendering','interrupted')",(now(),job_id))
        database.execute("UPDATE items SET status='cancelled',active_job=NULL WHERE id=? AND active_job=?",(job['item_id'],job_id))
        return {'ok':True}

    @app.get('/api/lists')
    def lists():
        return {'lists':database.rows('SELECT l.*,count(i.id) AS count FROM lists l LEFT JOIN memberships m ON m.list_id=l.id LEFT JOIN items i ON i.id=m.item_id AND i.deleted_at IS NULL GROUP BY l.id ORDER BY l.name')}

    @app.post('/api/lists')
    def make_list(body: ListName):
        name = body.name.strip()
        if not name or database.one('SELECT id FROM lists WHERE name=?',(name,)):
            raise WorkError('list_name','비어 있거나 이미 사용 중인 목록 이름입니다.')
        identifier = uuid.uuid4().hex
        database.execute('INSERT INTO lists VALUES (?,?,?)',(identifier,name,now()))
        return {'id':identifier,'name':name}

    @app.patch('/api/lists/{list_id}')
    def rename_list(list_id: str, body: ListName):
        check_lists([list_id])
        name = body.name.strip()
        if not name or database.one('SELECT id FROM lists WHERE name=? AND id!=?',(name,list_id)):
            raise WorkError('list_name','비어 있거나 이미 사용 중인 목록 이름입니다.')
        database.execute('UPDATE lists SET name=? WHERE id=?',(name,list_id))
        return {'ok':True}

    @app.delete('/api/lists/{list_id}')
    def delete_list(list_id: str):
        check_lists([list_id])
        database.execute('DELETE FROM lists WHERE id=?',(list_id,))
        return {'ok':True,'message':'목록만 삭제했습니다. 자료와 원문·결과물은 유지됩니다.'}

    @app.get('/api/settings')
    def settings():
        value = database.settings()
        return {'settings':value,'engine_status':ai.status(value),'api_key_present':bool(secret_store.get(value['base_url'])),
                'data_dir':str(database.root),'config_dir':str(secret_store.path.parent),
                'pending_cleanup':len(pending_deletions(database)),
                'test_mode':bool(getattr(ai,'is_test_double',False))}

    @app.put('/api/settings')
    def save_settings(body: EngineSettings):
        url = urlsplit(body.base_url)
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise WorkError('invalid_endpoint','인증 정보나 쿼리가 없는 올바른 AI 서버 주소를 입력해 주세요.')
        try:
            port=url.port
        except ValueError:
            raise WorkError('invalid_endpoint','AI 서버의 포트 번호가 올바르지 않습니다.')
        if port==0:
            raise WorkError('invalid_endpoint','AI 서버의 포트 번호가 올바르지 않습니다.')
        if url.scheme!='https' and url.hostname not in ('127.0.0.1','localhost','::1'):
            raise WorkError('invalid_endpoint','외부 AI 서버는 HTTPS 주소를 사용해 주세요.')
        if body.clear_api_key:
            secret_store.set('')
        elif body.api_key is not None and body.api_key.strip():
            secret_store.set(body.api_key.strip(),body.base_url)
        database.save_settings(body.model_dump(exclude={'api_key','clear_api_key'}))
        return {'ok':True,'message':'설정했습니다. 연결 테스트는 실제 AI를 한 번 호출합니다.'}

    @app.post('/api/engine/test')
    def test_engine():
        return ai.test(database.settings(),database.root/'work')

    @app.post('/api/engine/login')
    def login_engine():
        executable = codex_command()
        if not executable:
            raise WorkError('engine_missing','Codex CLI가 없습니다. 설치 스크립트에서 Codex 설치를 선택하거나 API를 사용해 주세요.')
        try:
            flags = subprocess.CREATE_NEW_CONSOLE if os.name=='nt' else 0
            subprocess.Popen(codex_arguments('login'),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,creationflags=flags)
        except OSError:
            raise WorkError('ai_auth','로그인 브라우저를 시작하지 못했습니다.')
        return {'ok':True,'message':'로그인 브라우저를 시작했습니다. 로그인 후 설정을 다시 열어 상태를 확인해 주세요.'}

    @app.post('/api/backup')
    def backup():
        if worker.current_item:
            raise WorkError('busy','작업 파일을 정리 중입니다. 작업이 끝난 뒤 백업해 주세요.')
        directory = Path(tempfile.mkdtemp(prefix='chansum-download-'))
        target = directory/'chansum-backup.zip'
        try:
            create_backup(database,target,worker)
        except BaseException:
            shutil.rmtree(directory,ignore_errors=True)
            raise
        return FileResponse(target,media_type='application/zip',filename='Chansum-backup-'+now()[:10]+'.zip',
                            background=BackgroundTask(shutil.rmtree,directory,ignore_errors=True))

    @app.post('/api/restore')
    async def restore(file: UploadFile = File(...), confirm: str = Form('')):
        if confirm!='RESTORE':
            raise WorkError('confirmation','자료 전체 교체 범위를 확인한 뒤 복원해 주세요.')
        if worker.current_item:
            raise WorkError('busy','작업 파일을 정리 중입니다. 작업이 끝난 뒤 복원해 주세요.')
        if cleanup_deletions(database):
            raise WorkError('busy','잠긴 파일의 삭제가 남아 있습니다. 파일을 사용하는 프로그램을 닫고 앱을 다시 실행한 뒤 복원해 주세요.')
        with tempfile.TemporaryDirectory(prefix='chansum-upload-') as directory:
            path = Path(directory)/'backup.zip'
            length = 0
            with path.open('wb') as stream:
                while part := await file.read(1024*1024):
                    length += len(part)
                    if length>MAX_BACKUP:
                        raise WorkError('too_large','최대 512MB의 백업 파일을 선택해 주세요.')
                    stream.write(part)
            await file.close()
            result = await asyncio.to_thread(restore_backup,database,path,worker)
            worker.wakeup.set()
            return result

    app.mount('/static',StaticFiles(directory=ROOT/'chansum/static'),name='static')
    app.mount('/assets',StaticFiles(directory=ASSETS),name='assets')
    return app
