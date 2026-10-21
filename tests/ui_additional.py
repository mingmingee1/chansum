"""Duplicate handling, list CRUD, safe rendering, refreshed export inspection."""
import json
import re
import time
import uuid
from pathlib import Path

import fitz
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'test-results'
BASE='http://127.0.0.1:9420'


def wait_job(page,item_id,job_id):
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        data=page.request.get(BASE+'/api/items/'+item_id).json()
        job=next(j for j in data['jobs'] if j['id']==job_id)
        if job['status']=='complete':return data,job
        assert job['status'] not in ('failed','cancelled'),job
        page.wait_for_timeout(100)
    raise AssertionError('Job did not complete: '+str(job))


def run():
    record=json.loads((OUT/'ui-record.json').read_text())
    item_id=record['item_id'];suffix=uuid.uuid4().hex[:6]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium')
        page=browser.new_page(viewport={'width':1440,'height':1000},accept_downloads=True)
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        # Clean only disposable lists created by an earlier run of this test.
        page.goto(BASE,wait_until='networkidle')
        for disposable in page.request.get(BASE+'/api/lists').json()['lists']:
            if re.fullmatch(r'(임시 목록|이름 변경 검증) [0-9a-f]{6}',disposable['name']):
                page.goto(BASE+'/#list/'+disposable['id'])
                page.get_by_role('button',name='목록 삭제',exact=True).click()
                page.get_by_role('button',name='목록만 삭제',exact=True).click()
                expect(page.get_by_role('heading',name='전체 라이브러리',exact=True)).to_be_visible()
        page.goto(BASE+'/#item/'+item_id,wait_until='networkidle')
        before=page.request.get(BASE+'/api/items/'+item_id).json()
        page.goto(BASE+'/#library',wait_until='networkidle')
        page.get_by_role('button',name='새 자료 추가',exact=True).first.click()
        original=(ROOT/'tests/fixtures/energy.txt').read_text()+'\n\n검증 실행 ID: '+record['suffix']
        page.locator('dialog input[type=file]').set_input_files({'name':'same.txt','mimeType':'text/plain','buffer':original.encode()})
        page.get_by_role('button',name='가져오기',exact=True).click()
        expect(page.locator('.duplicate-row')).to_have_count(1)
        page.get_by_role('button',name='기존 항목 열기',exact=True).click()
        expect(page.get_by_role('heading',name=record['title'],exact=True)).to_be_visible()
        assert len(page.request.get(BASE+'/api/items/'+item_id).json()['jobs'])==len(before['jobs'])
        page.locator('#new-list').click();page.get_by_label('목록 이름',exact=True).fill('임시 목록 '+suffix)
        page.get_by_role('button',name='만들기',exact=True).click()
        expect(page.get_by_role('heading',name='임시 목록 '+suffix,exact=True)).to_be_visible()
        temporary_list=page.url.split('#list/')[1]
        page.goto(BASE+'/#item/'+item_id)
        page.get_by_role('button',name='목록 분류',exact=True).click()
        page.locator('dialog').get_by_label('임시 목록 '+suffix,exact=True).check()
        page.locator('dialog').get_by_role('button',name='적용',exact=True).click()
        expect(page.locator('dialog')).to_have_count(0)
        assert len(page.request.get(BASE+'/api/items/'+item_id).json()['item']['lists'])==3
        page.goto(BASE+'/#list/'+temporary_list)
        page.get_by_role('button',name='이름 변경',exact=True).click()
        page.get_by_label('이름',exact=True).fill('이름 변경 검증 '+suffix)
        page.locator('dialog').get_by_role('button',name='저장',exact=True).click()
        expect(page.get_by_role('heading',name='이름 변경 검증 '+suffix,exact=True)).to_be_visible()
        page.get_by_role('button',name='목록 삭제',exact=True).click()
        page.get_by_role('button',name='목록만 삭제',exact=True).click()
        expect(page.get_by_role('heading',name='전체 라이브러리',exact=True)).to_be_visible()
        data=page.request.get(BASE+'/api/items/'+item_id).json()
        assert len(data['item']['lists'])==2 and data['summary']==before['summary']
        # Raw text that looks like script/HTML must stay text in both tabs.
        page.get_by_role('button',name='새 자료 추가',exact=True).first.click()
        name='안전 렌더링 검증 '+suffix
        payload='<script>window.chansumXss=1</script>\n\n<img src=x onerror="window.chansumXss=2"> 이 문자열은 원문 데이터이며 코드로 실행되면 안 된다. 근거 문단을 그대로 보관한다.\n\n검증 번호: '+suffix
        page.locator('dialog input[type=file]').set_input_files({'name':name+'.txt','mimeType':'text/plain','buffer':payload.encode()})
        with page.expect_response(lambda response:response.url.endswith('/items/files') and response.request.method=='POST') as added:
            page.get_by_role('button',name='가져오기',exact=True).click()
        assert added.value.json()['results'][0]['job_id']
        page.goto(BASE+'/#jobs')
        page.reload(wait_until='networkidle')
        row=page.locator('.job-row').filter(has=page.get_by_role('button',name=name,exact=True))
        expect(row.locator('.status.complete')).to_be_visible(timeout=90000)
        page.get_by_role('button',name=name,exact=True).click()
        expect(page.locator('.summary-section').first).to_be_visible()
        assert page.evaluate('window.chansumXss === undefined')
        page.get_by_role('tab',name='원문',exact=True).click()
        expect(page.locator('.source-segment').first).to_contain_text('<script>')
        assert page.evaluate('window.chansumXss === undefined')
        page.screenshot(path=str(OUT/'ui-safe-source.png'),full_page=True)
        page.get_by_role('button',name='휴지통으로',exact=True).click()
        page.locator('#primary-nav').get_by_role('link',name='휴지통',exact=True).click()
        page.get_by_role('checkbox',name=name+' 선택',exact=True).check()
        page.locator('.bulk-bar').get_by_role('button',name='영구 삭제',exact=True).click()
        page.locator('dialog').get_by_role('checkbox').check()
        page.locator('dialog').get_by_role('button',name='영구 삭제',exact=True).click()
        expect(page.locator('dialog')).to_have_count(0)
        # Re-export with the current renderer; assert the exact new job completed.
        page.goto(BASE+'/#item/'+item_id)
        page.get_by_role('button',name='재생성',exact=True).click()
        with page.expect_response(lambda r:r.url.endswith('/regenerate') and r.request.method=='POST') as response:
            page.locator('dialog').get_by_role('button',name='재생성',exact=True).click()
        data,job=wait_job(page,item_id,response.value.json()['job_id'])
        assert job['cache_hits']>0
        page.reload(wait_until='networkidle')
        for kind,filename in [('PNG','sample-infographic.png'),('PDF','sample-report.pdf')]:
            with page.expect_download() as info:page.get_by_role('link',name=kind+' 다운로드',exact=True).click()
            info.value.save_as(OUT/filename)
        assert not errors,errors
        browser.close()
    for path in OUT.glob('pdf-page-*.png'):path.unlink()
    document=fitz.open(OUT/'sample-report.pdf')
    for index,page in enumerate(document):
        page.get_pixmap(matrix=fitz.Matrix(1.25,1.25)).save(OUT/f'pdf-page-{index+1}.png')
        for block in page.get_text('blocks'):
            assert block[0]>=-1 and block[1]>=-1 and block[2]<=page.rect.width+1 and block[3]<=page.rect.height+1
    text=''.join(page.get_text() for page in document)
    assert '실제 AI 요약이 아닙니다' in text and '1,000' in text and '운동 에너지' in text
    fonts=sorted({font[3] for page in document for font in page.get_fonts()})
    links=sum(len(page.get_links()) for page in document)
    assert any('Noto' in font for font in fonts) and links>0
    (OUT/'pdf-check.json').write_text(json.dumps({'pages':len(document),'fonts':fonts,'links':links,'all_pages_rendered':True,'all_text_inside_page':True},ensure_ascii=False,indent=2))
    (OUT/'additional-ui-check.json').write_text(json.dumps({'duplicate_opens_existing_without_job':True,'list_create_rename_delete_keeps_document':True,'raw_script_not_executed':True,'reload_during_processing_keeps_job':True,'confirmed_permanent_delete':True,'regeneration_cache_hits':job['cache_hits'],'page_errors':errors},indent=2))
    print('Additional UI checks passed; current PDF pages:',len(document))


if __name__=='__main__':run()
