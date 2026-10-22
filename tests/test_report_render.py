import unicodedata
import copy
import json

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
    assert len(json.loads((tmp_path/'layout-check.json').read_text())['pages'])==1
    for topic in summary['report']['sections']:
        assert topic['heading'].replace(' ','') in cover.replace(' ','').replace('\n','')
    assert '인포그래픽 요약' in cover
    text=''.join(p.get_text() for p in doc).replace('\n','')
    assert 'W로표시한전력과J로표시한에너지는서로다른물리량' in ''.join(text.split())


def stress_bundle(kind):
    source,summary=bundle(kind)
    report=summary['report']
    if kind=='flow':
        topics=report['sections']
        report['sections']=topics+[copy.deepcopy(topics[0]),copy.deepcopy(topics[2])]
        for index,topic in enumerate(report['sections']):
            topic['heading']=f'주제 {index+1} · 같은 기준으로 자료를 비교하고 조건을 확인하는 방법'
            topic['digest']['text']='결과를 비교하려면 사용 시간과 운전 조건이 같은지 확인해야 합니다. 조건이 다르면 단순한 수치 차이만으로 전체 사용량이 더 적다고 단정할 수 없습니다.'
    else:
        report['visual']['series']=[copy.deepcopy(datum) for datum in report['visual']['series']*3]
        for index,datum in enumerate(report['visual']['series']):
            datum['label']='정격 전력을 같은 조건에서 측정한 비교 대상 장치 '+str(index+1)
    return source,summary


@pytest.mark.parametrize('kind',['flow','chart'])
def test_dense_infographics_paginate_without_clipping_or_overlapping(tmp_path,kind):
    source,summary=stress_bundle(kind)
    render_outputs(tmp_path,'stress',summary,source,'http://127.0.0.1:9417')
    layout=json.loads((tmp_path/'layout-check.json').read_text())['pages']
    assert len(layout)>=2
    assert all(p['height']<=1710 and not p['overlaps'] and not p['outside'] for p in layout)
    doc=fitz.open(tmp_path/'report.pdf')
    cover_text=''.join(p.get_text() for p in list(doc)[:len(layout)])
    for topic in summary['report']['sections']:
        assert ''.join(topic['heading'].split()) in ''.join(cover_text.split())
    if kind=='chart':
        for datum in summary['report']['visual']['series']:
            assert ''.join(datum['label'].split()) in ''.join(cover_text.split())
    for page in doc:
        for box in page.get_text('blocks'):
            assert box[0]>=0 and box[1]>=0 and box[2]<=page.rect.width+.5 and box[3]<=page.rect.height+.5
    assert (tmp_path/'infographic.svg').read_text().count('viewBox=')>=3
