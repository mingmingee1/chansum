"""Kill a fixture server mid-summary; verify automatic recovery in the UI."""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'test-results'


def run():
    suffix=uuid.uuid4().hex[:6]
    data=Path('/workspace')/('chansum-interruption-'+suffix)
    private=Path('/workspace')/('chansum-interruption-private-'+suffix)
    environment=os.environ.copy()
    environment.update({'CHANSUM_TEST_DATA':str(data),'CHANSUM_TEST_PRIVATE':str(private),'CHANSUM_PORT':'9424','CHANSUM_TEST_PORT':'9424','CHANSUM_TEST_DELAY':'12'})
    log=(OUT/'interruption-server.log').open('w')
    process=None
    def start():
        nonlocal process
        process=subprocess.Popen([sys.executable,'-m','tests.ui_server'],cwd=ROOT,env=environment,stdout=log,stderr=log)
        for _ in range(100):
            try:
                if httpx.get('http://127.0.0.1:9424/api/health',trust_env=False,timeout=.3).status_code==200:return
            except httpx.HTTPError:pass
            if process.poll() is not None:raise AssertionError('fixture server failed')
            time.sleep(.1)
        raise AssertionError('fixture server did not start')
    try:
        start()
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/chromium')
            page=browser.new_page(viewport={'width':1440,'height':1000})
            page.goto('http://127.0.0.1:9424',wait_until='networkidle')
            page.get_by_role('button',name='새 자료 추가',exact=True).first.click()
            content='검증용 실제 서버 중단 테스트: 서버가 요약 중에 종료되어도 수집된 원문과 작업 상태를 보존한다. 다음 실행에서 중단 사실을 식별하고 이어서 처리한다.'
            page.locator('dialog input[type=file]').set_input_files({'name':'서버 중단 검증.txt','mimeType':'text/plain','buffer':content.encode()})
            page.get_by_role('button',name='가져오기',exact=True).click()
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                jobs=httpx.get('http://127.0.0.1:9424/api/jobs',trust_env=False).json()['jobs']
                if jobs and jobs[0]['status']=='summarizing':break
                page.wait_for_timeout(100)
            job=jobs[0]
            assert job['status']=='summarizing',job
            before=httpx.get('http://127.0.0.1:9424/api/items/'+job['item_id'],trust_env=False).json()
            assert before['source'] and not before['summary']
            process.kill();process.wait(timeout=10)
            environment['CHANSUM_TEST_DELAY']='0'
            start()
            page.reload(wait_until='networkidle')
            expect(page.locator('.job-row .status.complete')).to_be_visible(timeout=90000)
            page.get_by_role('button',name='서버 중단 검증',exact=True).click()
            expect(page.get_by_role('tab',name='요약',exact=True)).to_be_visible()
            after=httpx.get('http://127.0.0.1:9424/api/items/'+job['item_id'],trust_env=False).json()
            assert after['jobs'][0]['resume_count']==1
            assert after['item']['source_path']==before['item']['source_path']
            assert after['summary'] and after['item']['status']=='complete'
            page.screenshot(path=str(OUT/'ui-interruption-resumed.png'),full_page=True)
            browser.close()
        (OUT/'interruption-check.json').write_text(json.dumps({'process_killed_during':'summarizing','resume_count':1,'same_source_path':True,'status':'complete','test_double':True},indent=2))
        print('Actual process interruption + browser reload + saved-source recovery passed.')
    finally:
        if process and process.poll() is None:
            process.terminate();process.wait(timeout=10)
        log.close()


if __name__=='__main__':run()
