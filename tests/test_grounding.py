import copy
import json

import pytest

from chansum.config import Secrets
from chansum.engine import Engine, validate_summary
from chansum.errors import WorkError
from chansum.grounding import check_grounding
from chansum.report import build_report, validate_plan
from tests.fixture_engine import FixtureEngine, fixture_plan
from tests.test_report import example


@pytest.mark.parametrize('original,output',[
    ('정격 전력은 100 W다.','정격 전력은 999 W다.'),
    ('정격 전력은 100 W다.','정격 전력은 100 kW다.'),
    ('정격 전력은 100 W다.','전력 밀도는 100 W/m²다.'),
    ('길이는 10 m다.','속도는 10 m/s다.'),
    ('전력은 약 100 W다.','전력은 100 W다.'),
    ('전력은 최대 100 W다.','전력은 100 W다.'),
    ('전력은 100 W 미만이다.','전력은 100 W 이하다.'),
    ('전력은 100 W 초과다.','전력은 100 W 이상이다.'),
    ('전력은 80~100 W다.','전력은 100 W다.'),
    ('전력은 100 W에서 200 W까지다.','전력은 100 W다.'),
    ('전력은 100 W부터 200 W까지다.','전력은 200 W다.'),
    ('조건에 따라 실패할 수 있다.','항상 성공하며 예외는 없다.'),
    ('같은 운전 조건에서 비교한다.','아무 조건 없이 비교한다.'),
])
def test_invented_quantity_unit_bound_and_absolute_are_rejected(original,output):
    with pytest.raises(WorkError):check_grounding(output,[original])


@pytest.mark.parametrize('original,output',[
    ('전력은 최대 100 W다.','전력은 100 W 이하입니다.'),
    ('참가비는 10,000원이다.','참가비 10000원'),
    ('계약 100 W','계약은 100 W다.'),
    ('시점별로 성립 여부가 달라진다.','항상 성립하지는 않는다.'),
    ('E=mc²',r'\(E=mc^2\)'),('x₁',r'\(x_1\)'),
    ('속도 10 m/s',r'속도는 10 m/s다.'),
])
def test_supported_rephrasing_and_math_notation(original,output):
    check_grounding(output,[original])


@pytest.mark.parametrize('field',['message','digest','overview','explanation','node_label'])
def test_valid_ids_do_not_approve_invented_report_values(field):
    source,_,units=example();plan=fixture_plan(units)
    if field=='node_label':
        plan['visual']['nodes'][0]['label']='장치 A의 999 W'
        with pytest.raises(WorkError):validate_plan(plan,units,source)
        return
    if field=='message':target=plan[field]
    elif field=='explanation':target=plan['sections'][0]['groups'][0]['entries'][0][field]
    else:target=plan['sections'][0][field]
    target.update(text='장치 A는 999 W로 작동한다.',claim_ids=[units[0]['id']])
    with pytest.raises(WorkError) as error:validate_plan(plan,units,source)
    assert error.value.code=='unsupported_report'


def test_extraction_checks_only_cited_chunk_text():
    source,results,_=example();bad=copy.deepcopy(results[0])
    bad['message']['text']='장치 A는 60 W다.'
    with pytest.raises(WorkError):validate_summary(bad,{s['id'] for s in source['segments']},source['segments'])


def test_extraction_repairs_once_and_does_not_retry_auth(tmp_path,monkeypatch):
    source,results,_=example();prompts=[];engine=Engine(Secrets(tmp_path/'private'))
    def adapter(prompt,*args):
        prompts.append(prompt);result=copy.deepcopy(results[0])
        if len(prompts)==1:result['message']['text']='장치 A는 999 W다.'
        return result
    monkeypatch.setattr(engine,'_http',adapter)
    engine.summarize(source['segments'],{}, {'engine':'openai'},tmp_path)
    assert len(prompts)==2 and '999' in prompts[1]
    prompts.clear()
    def rejected(*args):
        prompts.append('called');raise WorkError('ai_auth','인증 실패')
    monkeypatch.setattr(engine,'_http',rejected)
    with pytest.raises(WorkError):engine.summarize(source['segments'],{}, {'engine':'openai'},tmp_path)
    assert len(prompts)==1


@pytest.mark.parametrize('repair_succeeds',[True,False])
def test_editor_repair_is_bounded_and_only_success_is_cached(tmp_path,repair_succeeds):
    class RepairEngine(FixtureEngine):
        def edit_report(self,units,options,config,scratch):
            self.edit_calls+=1
            result=fixture_plan(units)
            if self.edit_calls==1 or not repair_succeeds:
                result['message']={'text':'장치 A는 999 W다.','claim_ids':[units[0]['id']]}
            else:assert '999' in options['_repair_feedback']
            return result
    source,results,_=example();engine=RepairEngine();cache=tmp_path/'cache'
    def run():return build_report(results,source,engine,{}, {},cache,tmp_path,lambda *x:None,lambda:None)
    if repair_succeeds:
        first,_=run();second,hits=run()
        assert first==second and hits==1 and len(list(cache.glob('report-*.json')))==1
    else:
        with pytest.raises(WorkError) as error:run()
        assert error.value.code=='unsupported_report' and not list(cache.glob('report-*.json'))
    assert engine.edit_calls==2
    assert json.loads((tmp_path/'quality-checks.json').read_text())['rejected'][0]['code']=='unsupported_report'
