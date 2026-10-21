"""Focused notes during completion, and stale CSRF after a server restart."""
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
BASE='http://127.0.0.1:9426'


def run():
    suffix=uuid.uuid4().hex[:6]
    environment=os.environ.copy()
    environment.update({'CHANSUM_TEST_DATA':'/workspace/chansum-notes-'+suffix,'CHANSUM_TEST_PRIVATE':'/workspace/chansum-notes-private-'+suffix,'CHANSUM_PORT':'9426','CHANSUM_TEST_PORT':'9426','CHANSUM_TEST_DELAY':'2'})
    log=(OUT/'notes-server.log').open('w');process=None
    def start():
        nonlocal process
        process=subprocess.Popen([sys.executable,'-m','tests.ui_server'],cwd=ROOT,env=environment,stdout=log,stderr=log)
        for _ in range(100):
            try:
                if httpx.get(BASE+'/api/health',trust_env=False,timeout=.3).status_code==200:return
            except httpx.HTTPError:pass
            time.sleep(.1)
        raise AssertionError('Server did not start')
    try:
        start()
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/chromium')
            page=browser.new_page(viewport={'width':1440,'height':1000})
            page.goto(BASE,wait_until='networkidle')
            page.get_by_role('button',name='새 자료 추가',exact=True).first.click()
            text='검증용 메모 입력이다. 요약이 완료되는 순간 메모를 입력하고 있어도 결과가 보존되어야 한다. 메모 입력을 마친 다음에는 완료된 요약과 다운로드 버튼이 자동으로 갱신되어야 한다.'
            page.locator('dialog input[type=file]').set_input_files({'name':'진행 중 메모.txt','mimeType':'text/plain','buffer':text.encode()})
            with page.expect_response(lambda r:r.url.endswith('/items/files') and r.request.method=='POST') as response:
                page.get_by_role('button',name='가져오기',exact=True).click()
            item_id=response.value.json()['results'][0]['id']
            page.goto(BASE+'/#item/'+item_id)
            note=page.get_by_label('자료 메모',exact=True);note.fill('완료 중에도 유지할 메모')
            assert page.evaluate("document.activeElement.id === 'item-note'")
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                data=page.request.get(BASE+'/api/items/'+item_id).json()
                if data['item']['status']=='complete':break
                assert data['item']['status']!='failed',data
                page.wait_for_timeout(100)
            assert data['item']['status']=='complete'
            assert page.evaluate("document.activeElement.id === 'item-note'")
            page.get_by_role('heading',name='진행 중 메모',exact=True).click()
            expect(page.locator('.summary-section').first).to_be_visible(timeout=10000)
            expect(page.get_by_label('자료 메모',exact=True)).to_have_value('완료 중에도 유지할 메모')
            process.terminate();process.wait(timeout=10)
            environment['CHANSUM_TEST_DELAY']='0';start()
            # Keep the original page open: its in-memory token is now stale.
            page.get_by_label('자료 메모',exact=True).fill('서버 재시작 후 새 토큰으로 저장한 메모')
            page.get_by_role('button',name='메모 저장',exact=True).click()
            expect(page.locator('#toast')).to_contain_text('메모를 저장했습니다',timeout=10000)
            data=page.request.get(BASE+'/api/items/'+item_id).json()
            assert data['item']['note']=='서버 재시작 후 새 토큰으로 저장한 메모'
            page.screenshot(path=str(OUT/'ui-notes-after-server-restart.png'),full_page=True)
            browser.close()
        (OUT/'notes-restart-check.json').write_text(json.dumps({'focused_notes_preserved_on_completion':True,'result_updates_after_blur':True,'stale_token_refreshed_after_restart':True,'note_saved_after_restart':True},indent=2))
        print('Notes on completion and stale-token recovery after server restart passed.')
    finally:
        if process and process.poll() is None:process.terminate();process.wait(timeout=10)
        log.close()


if __name__=='__main__':run()
