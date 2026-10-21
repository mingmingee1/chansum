import hashlib
import io
import os
import json
import threading
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chansum.app import create_app
from chansum.collect import captions, from_file, normalize_url
from chansum.config import write_json
from chansum.db import DB
from chansum.engine import cache_key, chunk_source, validate_summary
from chansum.errors import WorkError
from tests.fixture_engine import FixtureEngine


def fake_render(folder,item_id,summary,source,local_base):
    folder.mkdir(parents=True,exist_ok=True)
    write_json(folder/'summary.json',summary)
    for name in ('report.pdf','infographic.png','infographic.svg','report.html'):
        (folder/name).write_bytes(b'test output '+source['hash'].encode())


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr('chansum.jobs.render_outputs',fake_render)
    engine=FixtureEngine()
    app=create_app(tmp_path/'data',tmp_path/'private',engine)
    with TestClient(app) as client:
        client.headers['X-Chansum-Token']=client.get('/api/session').json()['token']
        yield client,app,engine,tmp_path


def upload(client,text=None,name='article.txt',lists=None):
    text=text or ('검증용 입력: 원문과 요약을 별도로 저장한다. 데이터는 로컬 디스크에 보관하고 각 문단을 근거 ID로 연결한다.\n\n조건: 작업 완료 전에 삭제되면 결과가 자료를 되살리지 않아야 한다.')
    response=client.post('/api/items/files',files={'files':(name,text.encode(),'text/plain')},data={'mode':'detail','list_ids':json.dumps(lists or [])})
    assert response.status_code==200,response.text
    return response.json()['results'][0]


def wait_item(client,item_id,statuses=('complete','partial','failed'),timeout=8):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        response=client.get('/api/items/'+item_id)
        if response.status_code==200 and response.json()['item']['status'] in statuses:
            return response.json()
        time.sleep(.03)
    raise AssertionError('worker did not reach terminal state: '+response.text)


def test_long_source_splits_and_preserves_every_character():
    source={'segments':[{'id':'p0001','text':'긴원문 조건 100 W 10초. '*1000}]}
    chunks=chunk_source(source,1000)
    assert len(chunks)>10
    assert ''.join(s['text'] for c in chunks for s in c)==source['segments'][0]['text']
    assert {s['id'] for c in chunks for s in c}=={'p0001'}
    assert all(sum(len(json.dumps(s,ensure_ascii=False)) for s in c)<=1000 for c in chunks)


def test_invalid_evidence_is_rejected():
    engine=FixtureEngine();engine.invalid=True
    with pytest.raises(WorkError,match='근거 구간 ID'):
        validate_summary(engine.summarize([{'id':'p0001','text':'정상 원문 설명이다.'}],{}, {},Path('/tmp')),{'p0001'})


def test_caption_timing_and_youtube_identity():
    segments=captions('WEBVTT\n\n00:00.000 --> 00:02.500\n첫 번째 자막이다.\n\n00:03.000 --> 00:05.000\n두 번째 자막이다.\n')
    assert [(s['id'],s['start'],s['duration']) for s in segments]==[('t0001',0,2.5),('t0002',3,2)]
    assert normalize_url('https://youtu.be/dQw4w9WgXcQ?t=10')[0]==normalize_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=share')[0]


def test_login_and_empty_html_not_accepted(tmp_path):
    file=tmp_path/'login.html';file.write_text('<html><article><h1>로그인</h1><p>로그인이 필요합니다. '+('Sign in to continue. '*20)+'</p></article></html>')
    with pytest.raises(WorkError):from_file(file,'login.html')
    file.write_text('<html><body></body></html>')
    with pytest.raises(WorkError):from_file(file,'empty.html')


def test_cache_lifecycle_and_failed_regeneration_preserves_results(setup):
    client,app,engine,_=setup
    added=upload(client);item=wait_item(client,added['id']);assert item['item']['status']=='complete'
    before=item['item']['result_path'];calls=engine.calls
    assert client.get('/api/items/'+added['id']+'/download/png').status_code==200
    assert client.get('/api/items/'+added['id']+'/download/pdf').status_code==200
    assert engine.calls==calls
    client.post('/api/items/'+added['id']+'/regenerate',json={'mode':'detail'})
    again=wait_item(client,added['id']);assert again['jobs'][0]['cache_hits']>=1;assert engine.calls==calls
    old_result=again['item']['result_path'];old_bytes=(app.state.db.root/old_result/'report.pdf').read_bytes()
    app.state.db.save_settings({'model':'changed-model'})
    engine.fail=True
    client.post('/api/items/'+added['id']+'/regenerate',json={'mode':'detail'})
    failed=wait_item(client,added['id']);assert failed['item']['status']=='failed'
    assert failed['item']['result_path']==old_result
    assert client.get('/api/items/'+added['id']+'/download/pdf').content==old_bytes
    assert engine.calls>calls


def test_duplicates_lists_search_notes_trash_restore_and_purge(setup):
    client,app,engine,_=setup
    one=client.post('/api/lists',json={'name':'읽기'}).json()['id']
    two=client.post('/api/lists',json={'name':'연구'}).json()['id']
    added=upload(client,lists=[one]);wait_item(client,added['id']);duplicate=upload(client)
    assert duplicate['duplicate'] and duplicate['id']==added['id']
    client.patch('/api/items/'+added['id'],json={'title':'에너지 100%','note':'다시 읽을 문서','favorite':True})
    assert len(client.get('/api/items',params={'q':'100%'}).json()['items'])==1
    assert len(client.get('/api/items',params={'q':'다시 읽을'}).json()['items'])==1
    client.post('/api/items/bulk',json={'ids':[added['id']],'action':'lists_add','list_ids':[two]})
    assert len(client.get('/api/items/'+added['id']).json()['item']['lists'])==2
    assert len(list((app.state.db.root/'items').iterdir()))==1
    client.post('/api/items/bulk',json={'ids':[added['id']],'action':'trash'})
    assert not client.get('/api/items').json()['items']
    assert len(client.get('/api/items',params={'trash':True}).json()['items'])==1
    assert client.post('/api/items/bulk',json={'ids':[added['id']],'action':'purge'}).status_code==400
    client.post('/api/items/bulk',json={'ids':[added['id']],'action':'restore'})
    assert len(client.get('/api/items/'+added['id']).json()['item']['lists'])==2
    client.delete('/api/lists/'+one)
    assert client.get('/api/items/'+added['id']).status_code==200
    client.post('/api/items/bulk',json={'ids':[added['id']],'action':'lists_remove','list_ids':[two]})
    assert not client.get('/api/items/'+added['id']).json()['item']['lists']
    client.post('/api/items/bulk',json={'ids':[added['id']],'action':'trash'})
    client.post('/api/items/bulk',json={'ids':[added['id']],'action':'purge','confirm':'DELETE'})
    assert not (app.state.db.root/'items'/added['id']).exists()


def test_invalid_id_causes_real_failed_state(setup):
    client,app,engine,_=setup;engine.invalid=True
    item=wait_item(client,upload(client)['id'])
    assert item['item']['status']=='failed' and item['item']['error_code']=='invalid_evidence'
    assert item['source'] and not item['summary']


def test_partial_summary_reports_missing_chunks(setup):
    client,app,engine,_=setup
    app.state.db.save_settings({'chunk_chars':1000});engine.fail_at=2
    text='\n\n'.join(('문단 '+str(i)+'의 조건과 예외를 설명한다. '+('실제 근거에만 연결한다. '*20)) for i in range(8))
    result=wait_item(client,upload(client,text)['id'])
    assert result['item']['status']=='partial'
    assert result['summary']['failed_chunks']==1 and result['summary']['missing_segments']


def test_delete_during_work_cannot_resurrect_item(setup):
    client,app,engine,_=setup
    engine.block=threading.Event();added=upload(client)
    assert engine.started.wait(5)
    client.post('/api/items/bulk',json={'ids':[added['id']],'action':'trash'})
    client.post('/api/items/bulk',json={'ids':[added['id']],'action':'purge','confirm':'DELETE'})
    engine.block.set()
    deadline=time.monotonic()+5
    while app.state.worker.current_item and time.monotonic()<deadline:time.sleep(.03)
    assert not app.state.db.item(added['id'])
    assert not (app.state.db.root/'items'/added['id']).exists()


def test_interrupted_job_resumes_and_data_persists(tmp_path,monkeypatch):
    monkeypatch.setattr('chansum.jobs.render_outputs',fake_render)
    root,private=tmp_path/'data',tmp_path/'private'
    first=create_app(root,private,FixtureEngine(),start_worker=False)
    with TestClient(first) as client:
        client.headers['X-Chansum-Token']=client.get('/api/session').json()['token']
        added=upload(client)
        first.state.db.execute("UPDATE jobs SET status='summarizing',stage='summarizing' WHERE id=?",(added['job_id'],))
    second=create_app(root,private,FixtureEngine())
    with TestClient(second) as client:
        result=wait_item(client,added['id'])
        assert result['item']['status']=='complete'
        assert result['jobs'][0]['resume_count']==1
        assert result['source'] and result['summary']


def test_backup_restore_separate_location_and_no_secrets(setup,tmp_path,monkeypatch):
    client,app,engine,_=setup
    body={'engine':'openai','model':'test-model','api_key':'PRIVATE-KEY-DO-NOT-BACKUP'}
    assert client.put('/api/settings',json=body).status_code==200
    assert b'PRIVATE-KEY' not in client.get('/api/settings').content
    added=upload(client);wait_item(client,added['id'])
    client.patch('/api/items/'+added['id'],json={'note':'복원 확인 메모'})
    backup=client.post('/api/backup');assert backup.status_code==200
    with zipfile.ZipFile(io.BytesIO(backup.content)) as archive:
        assert 'manifest.json' in archive.namelist()
        assert all(b'PRIVATE-KEY-DO-NOT-BACKUP' not in archive.read(name) for name in archive.namelist())
    restored=create_app(tmp_path/'restored-data',tmp_path/'restored-private',FixtureEngine())
    with TestClient(restored) as other:
        other.headers['X-Chansum-Token']=other.get('/api/session').json()['token']
        response=other.post('/api/restore',files={'file':('backup.zip',backup.content)},data={'confirm':'RESTORE'})
        assert response.status_code==200,response.text
        result=other.get('/api/items/'+added['id']).json()
        assert result['item']['note']=='복원 확인 메모' and result['source'] and result['summary']
        assert other.get('/api/items/'+added['id']+'/download/pdf').status_code==200
        assert not other.get('/api/settings').json()['api_key_present']


def test_backup_path_traversal_rejected(setup):
    client,app,engine,tmp_path=setup
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        archive.writestr('../outside.txt','bad')
        archive.writestr('manifest.json','{}')
    response=client.post('/api/restore',files={'file':('bad.zip',stream.getvalue())},data={'confirm':'RESTORE'})
    assert response.status_code==400
    assert not (tmp_path/'outside.txt').exists()


def test_csrf_and_host_check_and_settings_endpoint(setup):
    client,app,engine,_=setup
    assert client.post('/api/lists',json={'name':'위조'},headers={'X-Chansum-Token':'wrong'}).status_code==403
    assert client.post('/api/lists',json={'name':'위조'},headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/health',headers={'Host':'evil.example'}).status_code==403
    assert client.put('/api/settings',json={'engine':'openai','base_url':'https://user:password@example.com','model':'x'}).status_code==400
    assert client.put('/api/settings',json={'engine':'openai','base_url':'http://example.com','model':'x'}).status_code==400


def test_collection_failure_kept_and_can_retry(setup,monkeypatch):
    client,app,engine,_=setup
    def blocked(*a,**kw):raise WorkError('blocked','검증용 수집 차단')
    monkeypatch.setattr('chansum.collect.from_url',blocked)
    result=client.post('/api/items/urls',json={'urls':['https://example.com/article']}).json()['results'][0]
    item=wait_item(client,result['id'])
    assert item['item']['status']=='failed' and item['item']['error_code']=='blocked'
    assert len(client.get('/api/items').json()['items'])==1
    assert client.post('/api/jobs/'+result['job_id']+'/retry').status_code==200


def test_output_failure_preserves_previous_generation(setup,monkeypatch):
    client,app,engine,_=setup
    added=upload(client);result=wait_item(client,added['id']);old=result['item']['result_path']
    def broken(*args):raise WorkError('output_failed','검증용 렌더링 실패')
    monkeypatch.setattr('chansum.jobs.render_outputs',broken)
    client.post('/api/items/'+added['id']+'/regenerate',json={'mode':'detail'})
    failed=wait_item(client,added['id'])
    assert failed['item']['status']=='failed' and failed['item']['result_path']==old
    assert failed['summary']==result['summary']


@pytest.mark.parametrize('extension,content',[
    ('srt','1\n00:00:01,000 --> 00:00:04,500\n전력 100 W를 10초 사용하면 에너지는 1,000 J이다.\n\n'),
    ('vtt','WEBVTT\n\n00:01.000 --> 00:04.500\n전력 100 W를 10초 사용하면 에너지는 1,000 J이다.\n\n'),
    ('html','<html><head><title>전력과 에너지</title></head><body><article><h1>전력과 에너지</h1><p>'+('전력 100 W를 10초 사용하면 소비 에너지는 1,000 J이다. 적용 조건과 단위를 확인한다. '*8)+'</p><script>window.pwned=true;</script></article></body></html>'),
],ids=['srt','vtt','html'])
def test_all_supported_source_formats(tmp_path,extension,content):
    path=tmp_path/('source.'+extension);path.write_text(content)
    source=from_file(path,path.name)
    assert source['segments'] and source['hash']
    assert any('100 W' in segment['text'] for segment in source['segments'])
    if extension in ('srt','vtt'):
        assert source['segments'][0]['start']==1 and source['segments'][0]['duration']==3.5
    else:
        assert all('window.pwned' not in s['text'] for s in source['segments'])


@pytest.mark.parametrize('codes,expected_calls,error_code',[
    ([429,200],2,None),([403],1,'blocked'),([503,503],2,'server_error')
])
def test_network_retry_policy(monkeypatch,codes,expected_calls,error_code):
    import httpx
    from chansum import collect
    calls=[]
    def handler(request):
        code=codes[min(len(calls),len(codes)-1)];calls.append(code)
        return httpx.Response(code,content=b'actual response body',headers={'Content-Type':'text/html'})
    client_type=httpx.Client
    monkeypatch.setattr(collect,'check_public_url',lambda url:None)
    monkeypatch.setattr(collect.time,'sleep',lambda duration:None)
    monkeypatch.setattr(collect.httpx,'Client',lambda **kw:client_type(transport=httpx.MockTransport(handler),**kw))
    if error_code:
        with pytest.raises(WorkError) as caught:collect.fetch_url('https://example.com/article')
        assert caught.value.code==error_code
    else:
        assert collect.fetch_url('https://example.com/article')[0]==b'actual response body'
    assert len(calls)==expected_calls


@pytest.mark.parametrize('engine_kind',['openai','ollama'])
def test_http_engine_schema_auth_and_evidence_validation(tmp_path,monkeypatch,engine_kind):
    import httpx
    from chansum.engine import Engine
    from chansum.config import Secrets
    store=Secrets(tmp_path/'private');store.set('TEST-KEY','https://example.com/v1')
    engine=Engine(store)
    segments=[{'id':'p0001','text':'전력 100 W를 10초 사용하면 에너지는 1,000 J이다.'}]
    value=FixtureEngine().summarize(segments,{}, {},tmp_path)
    calls=[]
    def handler(request):
        calls.append(request)
        payload=json.loads(request.content)
        if engine_kind=='openai':
            assert payload['response_format']['json_schema']['strict']
            assert request.headers['Authorization']=='Bearer TEST-KEY'
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(value)},'finish_reason':'stop'}]})
        assert payload['options']=={'num_ctx':32768,'num_predict':8192}
        assert payload['format']['additionalProperties'] is False
        return httpx.Response(200,json={'message':{'content':json.dumps(value)},'done_reason':'stop'})
    client_type=httpx.Client
    monkeypatch.setattr('chansum.engine.httpx.Client',lambda **kw:client_type(transport=httpx.MockTransport(handler),**kw))
    result=engine.summarize(segments,{'mode':'detail'},{'engine':engine_kind,'model':'test-model','base_url':'https://example.com/v1','timeout':20},tmp_path)
    assert result['message']['sources']==['p0001'] and len(calls)==1


def test_secret_directory_cannot_be_inside_backed_up_data(tmp_path):
    with pytest.raises(WorkError,match='겹치지 않는'):
        create_app(tmp_path/'data',tmp_path/'data/items/private')


def test_backup_waits_for_cancelled_worker_to_stop_writing(setup):
    client,app,engine,_=setup
    engine.block=threading.Event()
    try:
        added=upload(client)
        assert engine.started.wait(5)
        client.post('/api/jobs/'+added['job_id']+'/cancel')
        assert client.post('/api/backup').status_code==409
    finally:
        engine.block.set()


def test_multiple_selection_filter_and_sort(setup):
    client,app,engine,_=setup
    one=upload(client,'첫 번째 검증 자료다. 여러 자료를 선택해서 목록을 분류하고 삭제할 수 있어야 한다.','z.txt')['id']
    two=upload(client,'두 번째 검증 자료다. 여러 자료를 선택해도 실제 원문 파일은 각 자료에 한 번만 존재한다.','a.txt')['id']
    wait_item(client,one);wait_item(client,two)
    listed=client.get('/api/items',params={'sort':'title','kind':'file'}).json()['items']
    assert [i['id'] for i in listed]==[two,one]
    assert not client.get('/api/items',params={'kind':'youtube'}).json()['items']
    client.post('/api/items/bulk',json={'ids':[one,two],'action':'favorite'})
    assert len(client.get('/api/items',params={'favorite':True}).json()['items'])==2
    client.post('/api/items/bulk',json={'ids':[one,two],'action':'trash'})
    assert len(client.get('/api/items',params={'trash':True}).json()['items'])==2
    client.post('/api/items/bulk',json={'ids':[one,two],'action':'restore'})
    assert len(client.get('/api/items').json()['items'])==2


def test_windows_npm_codex_uses_node_without_shell(tmp_path,monkeypatch):
    from chansum import config
    install=tmp_path/'folder with spaces & literal symbols'
    script=install/'node_modules/@openai/codex/bin/codex.js'
    script.parent.mkdir(parents=True);script.write_text('// fixture entry point')
    monkeypatch.setattr(config,'codex_command',lambda:str(install/'codex.cmd'))
    monkeypatch.setattr(config.shutil,'which',lambda name:'/test/node.exe' if name=='node' else None)
    args=config.codex_arguments('exec','--model','model-name')
    assert args==['/test/node.exe',str(script),'exec','--model','model-name']
    script.unlink()
    with pytest.raises(OSError):config.codex_arguments('exec','--model','untrusted & argument')


def altered_backup(content,tmp_path,mutate):
    import sqlite3
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        files={name:archive.read(name) for name in archive.namelist() if name!='manifest.json'}
        manifest=json.loads(archive.read('manifest.json'))
    snapshot=tmp_path/'altered.sqlite3';snapshot.write_bytes(files['library.sqlite3'])
    connection=sqlite3.connect(snapshot)
    try:
        mutate(connection);connection.commit()
    finally:connection.close()
    files['library.sqlite3']=snapshot.read_bytes()
    manifest['files']={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        for name,data in files.items():archive.writestr(name,data)
        archive.writestr('manifest.json',json.dumps(manifest))
    return stream.getvalue()


def test_backup_cannot_introduce_path_traversal_item_id(setup,tmp_path):
    client,app,engine,_=setup
    added=upload(client);wait_item(client,added['id'])
    original=client.post('/api/backup').content
    def corrupt(connection):
        connection.execute('DELETE FROM jobs');connection.execute('DELETE FROM memberships')
        connection.execute("UPDATE items SET id='../../private',source_path=NULL,result_path=NULL,thumbnail=NULL,active_job=NULL")
    content=altered_backup(original,tmp_path,corrupt)
    guard=tmp_path/'private/guard.txt';guard.parent.mkdir(exist_ok=True);guard.write_text('keep')
    response=client.post('/api/restore',files={'file':('backup.zip',content)},data={'confirm':'RESTORE'})
    assert response.status_code==400 and response.json()['code']=='invalid_backup'
    assert guard.read_text()=='keep' and client.get('/api/items/'+added['id']).status_code==200


def test_api_keys_never_follow_a_changed_origin(tmp_path,monkeypatch):
    from chansum.config import Secrets
    store=Secrets(tmp_path/'private');store.set('TEST-BOUND-KEY','https://trusted.example/v1')
    assert store.get('https://trusted.example:443/new-api')=='TEST-BOUND-KEY'
    assert store.get('https://different.example/v1')==''
    assert store.get('http://trusted.example/v1')==''
    monkeypatch.setenv('CHANSUM_API_KEY','TEST-ENV-KEY')
    assert store.get('https://api.openai.com/v1')=='TEST-ENV-KEY'
    assert store.get('https://different.example')==''
    assert store.get('https://trusted.example/v1')=='TEST-BOUND-KEY'


def test_restored_unfinished_jobs_need_explicit_retry(setup,tmp_path):
    client,app,engine,_=setup
    added=upload(client);wait_item(client,added['id'])
    backup=client.post('/api/backup').content
    def interrupt(connection):
        connection.execute("UPDATE jobs SET status='summarizing',stage='summarizing'")
        connection.execute("UPDATE items SET status='summarizing'")
    content=altered_backup(backup,tmp_path,interrupt)
    other_engine=FixtureEngine()
    target=create_app(tmp_path/'recovered',tmp_path/'recovered-private',other_engine)
    with TestClient(target) as other:
        other.headers['X-Chansum-Token']=other.get('/api/session').json()['token']
        response=other.post('/api/restore',files={'file':('backup.zip',content)},data={'confirm':'RESTORE'})
        assert response.status_code==200,response.text
        result=other.get('/api/items/'+added['id']).json()
        assert result['item']['status']=='cancelled' and result['item']['active_job'] is None
        assert result['jobs'][0]['error_code']=='restored_unfinished'
        assert result['summary'] and other_engine.calls==0
        assert other.post('/api/jobs/'+added['job_id']+'/retry').status_code==200
        assert wait_item(other,added['id'])['item']['status']=='complete'


def test_export_links_reject_executable_source_urls():
    from chansum.render import external_url,evidence_url
    assert external_url('javascript:alert(1)') is None
    assert external_url('https://user:password@example.com') is None
    source={'kind':'youtube','url':'javascript:alert(1)','segments':[{'id':'p0001','text':'원문','start':12}]}
    assert evidence_url('document',source,'p0001','http://127.0.0.1:9417')=='http://127.0.0.1:9417/#item/document/source/p0001'


@pytest.mark.parametrize('failure_stage',['collection','summary'])
def test_refresh_retry_uses_the_failed_jobs_acquisition_intent_and_source(setup,monkeypatch,failure_stage):
    from chansum.collect import finalize
    client,app,engine,_=setup
    count=[]
    def collect(url,*args):
        count.append(url)
        if len(count)==2 and failure_stage=='collection':raise WorkError('blocked','검증용 갱신 수집 실패')
        text=('첫 버전의 원문이다. 자료의 초기 상태와 기존 결과를 보존한다.' if len(count)==1 else
              '두 번째 원문이다. 갱신 후 실패한 작업을 재시도할 때 이 원문을 사용해야 한다.')
        return finalize({'title':'갱신 검증','url':url,'segments':[{'id':'p0001','text':text}]},'web')
    monkeypatch.setattr('chansum.collect.from_url',collect)
    added=client.post('/api/items/urls',json={'urls':['https://example.com/revision'],'mode':'detail'}).json()['results'][0]
    old=wait_item(client,added['id'])
    engine.fail=(failure_stage=='summary')
    client.post('/api/items/'+added['id']+'/regenerate',json={'mode':'detail','refresh':True})
    failed=wait_item(client,added['id'])
    assert failed['item']['status']=='failed'
    assert failed['item']['result_path']==old['item']['result_path']
    assert failed['source']['hash']==old['source']['hash']
    engine.fail=False
    response=client.post('/api/jobs/'+failed['jobs'][0]['id']+'/retry')
    assert response.status_code==200,response.text
    result=wait_item(client,added['id'])
    assert result['item']['status']=='complete'
    assert result['source']['hash']!=old['source']['hash']
    assert '두 번째' in result['source']['segments'][0]['text']
    assert len(count)==(3 if failure_stage=='collection' else 2)


def test_item_and_initial_job_are_one_transaction(setup,monkeypatch):
    client,app,engine,_=setup
    def fail(*a,**kw):raise WorkError('queue_failed','검증용 큐 저장 실패')
    monkeypatch.setattr('chansum.app.enqueue',fail)
    response=client.post('/api/items/files',files={'files':('input.txt','큐 저장 실패 시 자료만 대기 상태로 남으면 안 된다.'.encode())})
    assert response.status_code==200
    assert response.json()['rejected'][0]['code']=='queue_failed'
    assert app.state.db.rows('SELECT id FROM items')==[]
    assert app.state.db.rows('SELECT id FROM jobs')==[]
    assert not any((app.state.db.root/'items').glob('*/input/*'))


def test_locked_permanent_delete_is_durable_and_excluded_from_backup(setup,monkeypatch):
    from chansum import deletion
    client,app,engine,_=setup
    identifier=upload(client)['id'];wait_item(client,identifier)
    folder=app.state.db.root/'items'/identifier
    real=deletion.shutil.rmtree
    def locked(path,*a,**kw):
        if Path(path)==folder:return
        return real(path,*a,**kw)
    client.post('/api/items/bulk',json={'ids':[identifier],'action':'trash'})
    with monkeypatch.context() as patch:
        patch.setattr(deletion.shutil,'rmtree',locked)
        response=client.post('/api/items/bulk',json={'ids':[identifier],'action':'purge','confirm':'DELETE'})
        assert response.status_code==200 and response.json()['pending_cleanup']==1
        assert folder.exists() and not app.state.db.item(identifier)
        assert deletion.pending(app.state.db)==[identifier]
        backup=client.post('/api/backup')
        assert backup.status_code==200
        assert client.get('/api/settings').json()['pending_cleanup']==1
        assert client.post('/api/restore',files={'file':('backup.zip',backup.content)},data={'confirm':'RESTORE'}).status_code==409
        with zipfile.ZipFile(io.BytesIO(backup.content)) as archive:
            assert not any(name.startswith('items/'+identifier+'/') for name in archive.namelist())
    assert deletion.cleanup(app.state.db)==0
    assert not folder.exists() and not deletion.pending(app.state.db)


def test_delete_journal_does_not_remove_a_live_or_restored_item(setup):
    from chansum import deletion
    client,app,engine,_=setup
    identifier=upload(client)['id'];wait_item(client,identifier)
    folder=app.state.db.root/'items'/identifier
    deletion.mark(app.state.db,[identifier])
    assert deletion.cleanup(app.state.db)==0
    assert folder.exists() and client.get('/api/items/'+identifier).json()['summary']


def test_restore_preserves_device_ai_connection_settings(setup,tmp_path):
    client,app,engine,_=setup
    client.put('/api/settings',json={'engine':'openai','model':'trusted-model','base_url':'https://trusted.example/v1','api_key':'TEST-TRUSTED-KEY'})
    backup=client.post('/api/backup').content
    def redirect(connection):
        connection.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('base_url',json.dumps('https://other.example/v1')))
    content=altered_backup(backup,tmp_path,redirect)
    response=client.post('/api/restore',files={'file':('backup.zip',content)},data={'confirm':'RESTORE'})
    assert response.status_code==200,response.text
    settings=client.get('/api/settings').json()
    assert settings['settings']['base_url']=='https://trusted.example/v1'
    assert settings['api_key_present'] and engine.calls==0


@pytest.mark.skipif(os.name=='nt',reason='POSIX process-group execution check; Windows needs a real Windows host')
def test_cli_timeout_ends_its_owned_child_process_tree(tmp_path,monkeypatch):
    import sys
    from chansum import engine as module
    from chansum.config import Secrets
    pidfile=tmp_path/'child.pid'
    script=tmp_path/'stub_cli.py'
    script.write_text('import subprocess,sys,time,pathlib\nchild=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"])\npathlib.Path('+repr(str(pidfile))+').write_text(str(child.pid))\ntime.sleep(30)\n')
    monkeypatch.setattr(module,'codex_command',lambda:sys.executable)
    monkeypatch.setattr(module,'codex_arguments',lambda *args:[sys.executable,str(script),*args])
    start=time.monotonic()
    with pytest.raises(WorkError) as caught:
        module.Engine(Secrets(tmp_path/'private'))._codex('source data',{'timeout':.4,'model':''},tmp_path/'work')
    assert caught.value.code=='ai_timeout' and time.monotonic()-start<5
    child=int(pidfile.read_text())
    stat=Path('/proc')/str(child)/'stat'
    if stat.exists():assert stat.read_text().split()[2]=='Z'
