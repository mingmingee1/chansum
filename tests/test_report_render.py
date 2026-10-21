import unicodedata

import fitz
import pytest

from chansum.errors import WorkError
from chansum.render import render_outputs
from tests.report_examples import bundle


def test_three_column_comparison_multiple_sources_and_normalized_korean(tmp_path):
    source,summary=bundle()
    report=summary['report']
    report['title']=unicodedata.normalize('NFD','한글 제목과 세 가지 비교')
    visual=report['visual'];visual['columns'].append('확인 사항')
    for row in visual['rows']:
        row['cells'].append({'text':'같은 조건에서 원문의 값을 확인합니다.','sources':['p0002','p0003','p0004','p0006']})
    render_outputs(tmp_path,'sample',summary,source,'http://127.0.0.1:9417')
    doc=fitz.open(tmp_path/'report.pdf')
    assert '한글 제목과 세 가지 비교' in doc[0].get_text()
    assert len(doc[0].get_links())>=16
    assert len(doc)>=4
    for page in doc:
        for b in page.get_text('blocks'):
            assert b[0]>=0 and b[1]>=0 and b[2]<=page.rect.width+.5 and b[3]<=page.rect.height+.5


def test_wide_equation_in_topic_overview_rejects_output(tmp_path):
    source,summary=bundle()
    summary['report']['sections'][0]['overview']['text']='\\('+'x'*130+'\\)'
    with pytest.raises(WorkError) as caught:
        render_outputs(tmp_path,'sample',summary,source,'http://127.0.0.1:9417')
    assert caught.value.code=='output_layout'
    assert not (tmp_path/'report.pdf').exists()


def test_infographic_covers_every_topic_and_pdf_uses_edited_narrative(tmp_path):
    source,summary=bundle('concept')
    render_outputs(tmp_path,'sample',summary,source,'http://127.0.0.1:9417')
    doc=fitz.open(tmp_path/'report.pdf')
    cover=doc[0].get_text()
    for topic in summary['report']['sections']:
        assert topic['heading'].replace(' ','') in cover.replace(' ','').replace('\n','')
    assert '인포그래픽 요약' in cover
    text=''.join(p.get_text() for p in doc).replace('\n','')
    assert 'W로표시한전력과J로표시한에너지는서로다른물리량' in ''.join(text.split())
