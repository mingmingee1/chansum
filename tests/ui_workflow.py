"""Run against tests.ui_server (explicit, visibly labelled AI test double)."""
import json
import time
import uuid
from pathlib import Path

import fitz
from playwright.sync_api import expect, sync_playwright

ROOT=Path(__file__).resolve().parent.parent
RESULTS=ROOT/'test-results'
RESULTS.mkdir(exist_ok=True)


def run():
    suffix=uuid.uuid4().hex[:5]
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium')
        context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
        page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:9420',wait_until='networkidle')
        expect(page.locator('#test-banner')).to_be_visible()
        page.locator('#new-list').click();page.get_by_label('목록 이름',exact=True).fill('에너지 읽기 '+suffix)
        page.get_by_role('button',name='만들기',exact=True).click()
        expect(page.get_by_role('heading',name='에너지 읽기 '+suffix,exact=True)).to_be_visible()
        page.get_by_role('button',name='새 자료 추가',exact=True).first.click()
        expect(page.get_by_label('정리 방식',exact=True)).to_have_value('detail')
        content=(ROOT/'tests/fixtures/energy.txt').read_text()+'\n\n검증 실행 ID: '+suffix
        page.locator('dialog input[type=file]').set_input_files({'name':'에너지 검증 '+suffix+'.txt','mimeType':'text/plain','buffer':content.encode()})
        page.get_by_role('button',name='가져오기',exact=True).click()
        expect(page.get_by_role('heading',name='작업 현황',exact=True)).to_be_visible()
        page.screenshot(path=str(RESULTS/'ui-jobs.png'),full_page=True)
        job_row=page.locator('.job-row').filter(has=page.get_by_role('button',name='에너지 검증 '+suffix,exact=True))
        expect(job_row.locator('.status.complete')).to_be_visible(timeout=90000)
        page.get_by_role('button',name='에너지 검증 '+suffix,exact=True).click()
        expect(page.get_by_role('tab',name='요약',exact=True)).to_be_visible()
        expect(page.get_by_role('navigation',name='보고서 목차')).to_be_visible()
        expect(page.locator('.summary-visual img')).to_be_visible()
        assert page.locator('.summary-visual img').evaluate('(img)=>img.complete && img.naturalWidth===1200')
        page.get_by_role('navigation',name='보고서 목차').get_by_role('button').first.click()
        expect(page.locator('.report-topic').first).to_be_visible()
        item_id=page.url.split('#item/')[1].split('/')[0]
        page.get_by_role('button',name='제목 변경',exact=True).click()
        page.get_by_label('제목',exact=True).fill('에너지 읽기 노트 '+suffix)
        page.get_by_role('button',name='저장',exact=True).click()
        expect(page.get_by_role('heading',name='에너지 읽기 노트 '+suffix,exact=True)).to_be_visible()
        page.get_by_role('button',name='즐겨찾기',exact=True).click()
        expect(page.get_by_role('button',name='즐겨찾기 해제',exact=True)).to_be_visible()
        page.get_by_label('자료 메모',exact=True).fill('앱 재시작과 백업 복원 후에도 남아야 하는 메모 '+suffix)
        page.get_by_role('button',name='메모 저장',exact=True).click()
        page.screenshot(path=str(RESULTS/'ui-summary.png'),full_page=True)
        page.locator('.evidence-links button').first.click()
        expect(page.locator('.source-segment.highlight')).to_be_visible()
        page.get_by_role('tab',name='인포그래픽',exact=True).click()
        expect(page.locator('.output-image')).to_be_visible()
        page.screenshot(path=str(RESULTS/'ui-infographic.png'),full_page=True)
        for kind,name in [('PNG','sample-infographic.png'),('PDF','sample-report.pdf')]:
            with page.expect_download() as info:
                page.get_by_role('link',name=kind+' 다운로드',exact=True).click()
            info.value.save_as(RESULTS/name)
        page.get_by_role('tab',name='PDF',exact=True).click()
        expect(page.locator('.pdf-frame')).to_be_visible()
        page.get_by_role('button',name='재생성',exact=True).click()
        with page.expect_response(lambda response:response.url.endswith('/regenerate') and response.request.method=='POST') as info:
            page.locator('dialog').get_by_role('button',name='재생성',exact=True).click()
        regeneration_id=info.value.json()['job_id']
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            detail=page.request.get('http://127.0.0.1:9420/api/items/'+item_id).json()
            job=next(j for j in detail['jobs'] if j['id']==regeneration_id)
            if job['status']=='complete':break
            assert job['status'] not in ('failed','cancelled'),job
            page.wait_for_timeout(100)
        assert job['status']=='complete' and job['cache_hits']>0
        assert detail['item']['result_path'].endswith(regeneration_id)
        page.locator('#new-list').click();page.get_by_label('목록 이름',exact=True).fill('보관함 '+suffix)
        page.get_by_role('button',name='만들기',exact=True).click()
        expect(page.get_by_role('heading',name='보관함 '+suffix,exact=True)).to_be_visible()
        page.goto('http://127.0.0.1:9420/#item/'+item_id)
        page.get_by_role('button',name='목록 분류',exact=True).click()
        page.locator('dialog').get_by_label('보관함 '+suffix,exact=True).check()
        page.locator('dialog').get_by_role('button',name='적용',exact=True).click()
        page.locator('#primary-nav').get_by_role('link',name='전체 라이브러리',exact=True).click()
        page.get_by_label('라이브러리 검색',exact=True).fill('에너지 읽기 노트 '+suffix)
        expect(page.locator('.library-table tbody tr')).to_have_count(1)
        page.get_by_label('자료 유형',exact=True).select_option('file')
        page.get_by_label('정렬',exact=True).select_option('title')
        page.screenshot(path=str(RESULTS/'ui-library.png'),full_page=True)
        page.get_by_role('checkbox',name='자료 전체 선택',exact=True).check()
        page.locator('.bulk-bar').get_by_role('button',name='휴지통으로',exact=True).click()
        expect(page.locator('.library-table tbody tr')).to_have_count(0)
        page.locator('#primary-nav').get_by_role('link',name='휴지통',exact=True).click()
        expect(page.locator('.library-table tbody tr')).to_have_count(1)
        page.get_by_role('checkbox',name='자료 전체 선택',exact=True).check()
        page.locator('.bulk-bar').get_by_role('button',name='복원',exact=True).click()
        page.locator('#primary-nav').get_by_role('link',name='전체 라이브러리',exact=True).click()
        expect(page.locator('.library-table tbody tr')).to_have_count(1)
        detail=page.request.get('http://127.0.0.1:9420/api/items/'+item_id).json()
        assert len(detail['item']['lists'])==2 and suffix in detail['item']['note']
        page.locator('#settings-link').click()
        expect(page.get_by_role('heading',name='설정 및 백업',exact=True)).to_be_visible()
        with page.expect_download() as info:
            page.get_by_role('button',name='백업 다운로드',exact=True).click()
        info.value.save_as(RESULTS/'sample-backup.zip')
        page.screenshot(path=str(RESULTS/'ui-settings.png'),full_page=True)
        (RESULTS/'ui-record.json').write_text(json.dumps({'item_id':item_id,'suffix':suffix,'title':detail['item']['title'],'note':detail['item']['note'],'lists':detail['item']['lists'],'page_errors':errors},ensure_ascii=False,indent=2))
        assert not errors,errors
        browser.close()
    doc=fitz.open(RESULTS/'sample-report.pdf')
    assert doc.page_count>=3
    text=''.join(page.get_text() for page in doc)
    assert '운동 에너지' in text and '1,000' in text and '조건' in text and '예외' in text
    assert '실제 AI 요약이 아닙니다' in text
    assert any(page.get_links() for page in doc)
    fonts={font[3] for page in doc for font in page.get_fonts()}
    assert any('Noto' in name for name in fonts),fonts
    for index,page in enumerate(doc):
        page.get_pixmap(matrix=fitz.Matrix(1.25,1.25)).save(RESULTS/f'pdf-page-{index+1}.png')
        assert page.rect.width<page.rect.height
        for block in page.get_text('blocks'):
            assert block[0]>=-1 and block[1]>=-1 and block[2]<=page.rect.width+1 and block[3]<=page.rect.height+1
    (RESULTS/'pdf-check.json').write_text(json.dumps({'pages':doc.page_count,'fonts':sorted(fonts),'links':sum(len(p.get_links()) for p in doc),'all_pages_rendered':True},ensure_ascii=False,indent=2))
    print('UI flow passed; PDF pages:',doc.page_count,'fonts:',fonts)


if __name__=='__main__':run()
