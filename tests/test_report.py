import copy
import json
from pathlib import Path

import pytest

from chansum.collect import finalize
from chansum.errors import Cancelled, WorkError
from chansum.report import (build_report, edit_prompt, evidence_units, materialize,
                            validate_plan)
from tests.fixture_engine import FixtureEngine, fixture_plan
from tests.test_workflow import setup, upload, wait_item


def example():
    source=finalize({'title':'검증 자료','segments':[
        {'id':'p1','text':'장치 A의 정격 전력은 100 W다. 10 s 동안 사용한다.'},
        {'id':'p2','text':'장치 B의 정격 전력은 60 W다.'},
        {'id':'p3','text':'조건: 전력은 같은 운전 상태에서 비교해야 한다.'},
        {'id':'p4','text':'예외: 기동 순간에는 정격 전력과 다른 값을 보일 수 있다.'}]},'file')
    items=[{'text':s['text'],'sources':[s['id']],'kind':('condition' if i==2 else 'exception' if i==3 else 'fact')} for i,s in enumerate(source['segments'])]
    results=[{'title':'첫 구간 제목','message':items[0],'layout':'comparison','sections':[{'heading':'내용','items':items}]}]
    units=evidence_units(results,source)
    return source,results,units


@pytest.mark.parametrize('mutation,code',[
    ('missing','report_coverage'),('duplicate','report_coverage'),('invented','invalid_report_evidence')])
def test_editor_rejects_omission_duplicate_and_invalid_claim(mutation,code):
    source,_,units=example();plan=fixture_plan(units)
    entries=plan['sections'][0]['groups'][0]['entries']
    if mutation=='missing':entries.pop()
    elif mutation=='duplicate':entries.append(entries[0])
    else:plan['message']['claim_ids']=['absent']
    with pytest.raises(WorkError) as caught:validate_plan(plan,units,source)
    assert caught.value.code==code


def test_conditions_and_exceptions_stay_attached_to_their_claim():
    source,_,units=example();plan=fixture_plan(units)
    entries=plan['sections'][0]['groups'][0]['entries']
    entries[0]['support_ids']=[units[2]['id'],units[3]['id']]
    plan['sections'][0]['groups'][0]['entries']=entries[:2]
    report=materialize(validate_plan(plan,units,source),units)
    entry=report['sections'][0]['groups'][0]['entries'][0]
    assert [x['item']['kind'] for x in entry['supporting']]==['condition','exception']
    assert entry['supporting'][1]['item']['sources']==['p4']


def chart_plan(units):
    plan=fixture_plan(units)
    plan['visual']={'kind':'chart','title':'정격 전력 비교','nodes':[],'edges':[],'columns':[],'rows':[],'notes':[],
        'series':[{'label':'장치 A','value':100,'unit':'W','quote':'정격 전력은 100 W','claim_ids':[units[0]['id']]},
                  {'label':'장치 B','value':60,'unit':'W','quote':'정격 전력은 60 W','claim_ids':[units[1]['id']]}]}
    return plan


def test_chart_requires_matching_value_unit_and_literal_original_quote():
    source,_,units=example();plan=chart_plan(units)
    validate_plan(plan,units,source)
    plan['visual']['series'][0].update(value=10,quote=source['segments'][0]['text'])
    with pytest.raises(WorkError) as caught:validate_plan(plan,units,source)
    assert caught.value.code=='invalid_chart'
    plan['visual']['series'][0].update(value=100,quote='없는 원문에 100 W가 있다.')
    with pytest.raises(WorkError):validate_plan(plan,units,source)


@pytest.mark.parametrize('number',['약 100 W','80~100 W','80-100 W','80–100 W','100 W 이하','최대 100 W','≥100 W','-100 W','1100 W','100 W~120 W'])
@pytest.mark.parametrize('cropped',[False,True])
def test_chart_does_not_convert_estimate_range_or_bound_to_exact_value(number,cropped):
    source,_,units=example();source['segments'][0]['text']='전력은 '+number+'다.'
    plan=chart_plan(units);plan['visual']['series'][0]['quote']='100 W' if cropped else source['segments'][0]['text']
    with pytest.raises(WorkError) as caught:validate_plan(plan,units,source)
    assert caught.value.code=='invalid_chart'


def test_chart_qualifier_in_separate_sentence_does_not_reject_exact_value():
    source,_,units=example()
    source['segments'][0]['text']='최대 출력은 별도다. 정격 전력은 100 W다.'
    plan=chart_plan(units);plan['visual']['series'][0]['quote']='100 W'
    validate_plan(plan,units,source)


@pytest.mark.parametrize('text',['전력 밀도는 100 W/m²다.','측정값은 100 W²다.','100 W가 아니라 60 W다.'])
def test_chart_rejects_cropped_compound_unit_and_explicitly_negated_number(text):
    source,_,units=example();source['segments'][0]['text']=text
    plan=chart_plan(units);plan['visual']['series'][0]['quote']='100 W'
    with pytest.raises(WorkError) as caught:validate_plan(plan,units,source)
    assert caught.value.code=='invalid_chart'


def test_chart_does_not_treat_contract_word_as_approximation():
    source,_,units=example();source['segments'][0]['text']='계약 전력은 100 W다.'
    plan=chart_plan(units);plan['visual']['series'][0]['quote']='100 W'
    validate_plan(plan,units,source)


def test_editor_receives_original_quotes_even_when_extraction_paraphrases():
    source,results,_=example();results[0]['sections'][0]['items'][1]['text']='B는 60 W의 전력으로 동작한다.'
    units=evidence_units(results,source);prompt=edit_prompt(units)
    assert '장치 B의 정격 전력은 60 W다.' in prompt
    assert 'B는 60 W의 전력으로 동작한다.' in prompt


def test_edited_explanation_is_preserved_separately_from_extracted_evidence():
    source,_,units=example();plan=fixture_plan(units)
    narrative={'text':'장치 A의 100 W는 정격 운전 상태의 전력입니다. 기동 순간의 값과 구분해야 하므로 이 값을 모든 시점에 그대로 적용할 수는 없습니다.',
               'claim_ids':[units[0]['id'],units[3]['id']]}
    plan['sections'][0]['groups'][0]['entries'][0]['explanation']=narrative
    report=materialize(validate_plan(plan,units,source),units)
    entry=report['sections'][0]['groups'][0]['entries'][0]
    assert entry['narrative']['text']==narrative['text']
    assert entry['narrative']['sources']==['p1','p4']
    assert entry['item']['text']==source['segments'][0]['text']


@pytest.mark.parametrize('target',['digest','narrative'])
def test_new_visual_digest_and_explanation_reject_unknown_evidence(target):
    source,_,units=example();plan=fixture_plan(units)
    value=plan['sections'][0]['digest'] if target=='digest' else plan['sections'][0]['groups'][0]['entries'][0]['explanation']
    value['claim_ids']=['invented']
    with pytest.raises(WorkError) as caught:validate_plan(plan,units,source)
    assert caught.value.code=='invalid_report_evidence'


def test_explanation_must_still_ground_its_primary_claim():
    source,_,units=example();plan=fixture_plan(units)
    plan['sections'][0]['groups'][0]['entries'][0]['explanation']['claim_ids']=[units[1]['id']]
    with pytest.raises(WorkError) as caught:validate_plan(plan,units,source)
    assert caught.value.code=='invalid_report_evidence'


def test_editor_mode_reaches_actual_adapter_and_changes_editing_instruction(tmp_path,monkeypatch):
    from chansum.engine import Engine
    from chansum.config import Secrets
    source,_,units=example();engine=Engine(Secrets(tmp_path/'private'));prompts=[]
    monkeypatch.setattr(engine,'_http',lambda prompt,*args:prompts.append(prompt) or fixture_plan(units))
    engine.edit_report(units,{'mode':'brief'},{'engine':'openai'},tmp_path)
    engine.edit_report(units,{'mode':'detail'},{'engine':'openai'},tmp_path)
    assert '핵심 요약 모드' in prompts[0] and '상세 정리 모드' in prompts[1]
    assert prompts[0]!=prompts[1]


class WholeDocumentEngine(FixtureEngine):
    def edit_report(self,units,options,config,scratch):
        self.edit_calls+=1
        result=fixture_plan(units)
        late=next((u for u in units if '마지막 예외' in u['text']),None)
        if late:
            ref={'text':'마지막 예외: 이 조건을 전체 결론에도 반영한다.','claim_ids':[late['id']]}
            result['title']='전체 문서의 결론과 마지막 예외'
            result['message']=ref
            result['sections'][-1]['overview']=ref
            result['visual']['notes']=[ref]
        return result


def leaf_items(report):
    def section(s):
        for group in s['groups']:
            for entry in group['entries']:yield from node(entry)
    def node(n):
        if 'item' in n:yield n['item']
        for child in n.get('children',[]):yield from section(child)
        for support in n.get('supporting',[]):yield from node(support)
    return [item for s in report['sections'] for item in section(s)]


def test_long_document_global_edit_preserves_late_exception_and_cached_tree(tmp_path):
    source,results,_=example()
    items=[{'text':f'{i}번째 원문의 중요한 내용. '+('근거와 설명을 함께 보존한다. '*35),
            'sources':[f'p{i}'],'kind':'fact'} for i in range(30)]
    items[-1]={'text':'마지막 예외: 이 조건을 전체 결론에도 반영한다.','sources':['p29'],'kind':'exception'}
    results[0]['message']=items[0];results[0]['sections'][0]['items']=items
    source['segments']=[{'id':v['sources'][0],'text':v['text']} for v in items]
    source['hash']='long-source';engine=WholeDocumentEngine();progress=[]
    run=tmp_path/'run';run.mkdir();cache=tmp_path/'cache'
    result,hits=build_report(results,source,engine,{'chunk_chars':1000},{},cache,run,lambda *x:progress.append(x),lambda:None)
    assert result['editing_passes']>1 and '마지막 예외' in result['message']['text']
    assert len(leaf_items(result))==30 and leaf_items(result)[-1]['kind']=='exception'
    assert 'p29' in result['message']['sources']
    calls=engine.edit_calls
    again,hits=build_report(results,source,engine,{'chunk_chars':1000},{},cache,run,lambda *x:None,lambda:None)
    assert again==result and hits==calls and engine.edit_calls==calls


def test_completed_editor_batches_resume_after_interruption(tmp_path):
    source,results,_=example()
    items=[{'text':str(i)+'번째 내용. '+('실제 원문을 보관하고 근거를 유지한다. '*50),'sources':[f'p{i}'],'kind':'fact'} for i in range(12)]
    results[0]['message']=items[0];results[0]['sections'][0]['items']=items
    source['segments']=[{'id':v['sources'][0],'text':v['text']} for v in items]
    engine=FixtureEngine();run=tmp_path/'run';run.mkdir();cache=tmp_path/'cache'
    def stop_after_first(stage,done,total):
        if done==1:raise Cancelled()
    with pytest.raises(Cancelled):build_report(results,source,engine,{'chunk_chars':1000},{},cache,run,stop_after_first,lambda:None)
    assert len(json.loads((run/'editing.json').read_text())['completed'])==1
    result,hits=build_report(results,source,engine,{'chunk_chars':1000},{},cache,run,lambda *args:None,lambda:None)
    assert hits>=1 and len(leaf_items(result))==12


def test_editing_failure_preserves_successful_pdf_and_can_retry_from_extraction_cache(setup):
    client,app,engine,_=setup
    identifier=upload(client)['id'];old=wait_item(client,identifier)
    pdf=client.get('/api/items/'+identifier+'/download/pdf').content
    for path in (app.state.db.root/'cache').glob('report-*.json'):path.unlink()
    calls=engine.calls;engine.edit_fail=True
    client.post('/api/items/'+identifier+'/regenerate',json={'mode':'detail'})
    failed=wait_item(client,identifier)
    assert failed['item']['status']=='failed' and failed['item']['error_code']=='invalid_report'
    assert failed['item']['result_path']==old['item']['result_path']
    assert client.get('/api/items/'+identifier+'/download/pdf').content==pdf and engine.calls==calls
    engine.edit_fail=False
    client.post('/api/jobs/'+failed['jobs'][0]['id']+'/retry')
    assert wait_item(client,identifier)['item']['status']=='complete' and engine.calls==calls


def test_delete_during_editing_cannot_resurrect_item(setup):
    import threading,time
    client,app,engine,_=setup;engine.edit_block=threading.Event()
    identifier=upload(client)['id'];assert engine.edit_started.wait(4)
    assert client.get('/api/items/'+identifier).json()['item']['status']=='editing'
    client.post('/api/items/bulk',json={'ids':[identifier],'action':'trash'})
    engine.edit_block.set()
    deadline=time.monotonic()+4
    while app.state.worker.current_item and time.monotonic()<deadline:time.sleep(.03)
    item=app.state.db.item(identifier)
    assert item['deleted_at'] and item['status']=='cancelled' and not item['result_path']


def test_report_api_uses_editor_schema_and_source_quotes(tmp_path,monkeypatch):
    import httpx
    from chansum.engine import Engine
    from chansum.config import Secrets
    source,_,units=example();plan=fixture_plan(units);real=httpx.Client
    def handle(request):
        payload=json.loads(request.content)
        schema=payload['response_format']['json_schema']
        assert schema['name']=='chansum_report' and schema['strict']
        assert 'visual' in schema['schema']['required']
        assert '정격 전력은 100 W' in payload['messages'][-1]['content']
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(plan)},'finish_reason':'stop'}]})
    monkeypatch.setattr('chansum.engine.httpx.Client',lambda **kw:real(transport=httpx.MockTransport(handle)))
    secrets=Secrets(tmp_path/'private');secrets.set('TEST-KEY')
    result=Engine(secrets).edit_report(units,{}, {'engine':'openai','model':'test','base_url':'https://api.openai.com/v1'},tmp_path)
    assert validate_plan(result,units,source)==plan
