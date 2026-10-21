"""Run after restarting the fixture server; restore via the browser to 9422."""
import json
from pathlib import Path

from playwright.sync_api import expect,sync_playwright

RESULTS=Path(__file__).resolve().parent.parent/'test-results'


def run():
    record=json.loads((RESULTS/'ui-record.json').read_text())
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium')
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.goto('http://127.0.0.1:9420/#item/'+record['item_id'],wait_until='networkidle')
        expect(page.get_by_role('heading',name=record['title'],exact=True)).to_be_visible()
        expect(page.get_by_label('자료 메모',exact=True)).to_have_value(record['note'])
        data=page.request.get('http://127.0.0.1:9420/api/items/'+record['item_id']).json()
        assert len(data['item']['lists'])==2 and data['summary'] and data['source']
        page.screenshot(path=str(RESULTS/'ui-after-restart.png'),full_page=True)
        page.goto('http://127.0.0.1:9422/#settings',wait_until='networkidle')
        page.get_by_label('복원할 Chansum 백업',exact=True).set_input_files(RESULTS/'sample-backup.zip')
        page.get_by_role('button',name='선택한 백업 복원',exact=True).click()
        page.locator('dialog').get_by_role('checkbox').check()
        page.locator('dialog').get_by_role('button',name='복원',exact=True).click()
        expect(page.locator('dialog')).to_have_count(0,timeout=20000)
        page.goto('http://127.0.0.1:9422/#item/'+record['item_id'],wait_until='networkidle')
        expect(page.get_by_role('heading',name=record['title'],exact=True)).to_be_visible()
        expect(page.get_by_label('자료 메모',exact=True)).to_have_value(record['note'])
        result=page.request.get('http://127.0.0.1:9422/api/items/'+record['item_id']).json()
        assert result['source']['hash']==data['source']['hash']
        assert result['summary']==data['summary']
        assert len(result['item']['lists'])==2
        assert page.request.get('http://127.0.0.1:9422/api/items/'+record['item_id']+'/download/pdf').body()==page.request.get('http://127.0.0.1:9420/api/items/'+record['item_id']+'/download/pdf').body()
        page.screenshot(path=str(RESULTS/'ui-after-restore.png'),full_page=True)
        browser.close()
    (RESULTS/'restart-restore-check.json').write_text(json.dumps({'restart_persistence':True,'separate_location_restore':True,'source_hash_equal':True,'summary_equal':True,'pdf_bytes_equal':True,'memberships_restored':2},indent=2))
    print('Browser restart persistence and separate-directory backup restore passed.')


if __name__=='__main__':run()
