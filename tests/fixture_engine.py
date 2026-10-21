"""Deterministic TEST DOUBLE. Never enabled by the production launcher."""
import threading
import time

from chansum.errors import WorkError


class FixtureEngine:
    is_test_double = True

    def __init__(self):
        self.calls = 0
        self.fail = False
        self.invalid = False
        self.fail_at = None
        self.block = None
        self.started = threading.Event()
        self.delay = 0
        self.edit_calls = 0
        self.edit_delay = 0
        self.edit_fail = False
        self.edit_invalid = False
        self.edit_block = None
        self.edit_started = threading.Event()

    def status(self, config):
        return {'available':True,'message':'검증용 AI 테스트 대역 — 실제 AI 호출 아님'}

    def test(self, config, scratch):
        return {'ok':True,'message':'테스트 대역입니다. 실제 AI 연결을 검증하지 않습니다.'}

    def summarize(self, segments, options, config, scratch):
        self.calls += 1
        self.started.set()
        if self.delay:
            time.sleep(self.delay)
        if self.block:
            self.block.wait(15)
        if self.fail or self.calls==self.fail_at:
            raise WorkError('ai_failed','검증을 위해 발생시킨 AI 호출 실패')
        items = [{'text':segment['text'],'sources':['NONEXISTENT' if self.invalid else segment['id']],
                  'kind':'formula' if '\\(' in segment['text'] else 'condition' if '조건' in segment['text'] else 'exception' if '예외' in segment['text'] else 'fact'} for segment in segments]
        return {'title':'검증용 자료 · 에너지와 저장 기술','message':items[0],'layout':'concept',
                'sections':[{'heading':'원문 근거 · '+segment['id'],'items':[item]} for segment,item in zip(segments,items)]}

    def edit_report(self, units, options, config, scratch):
        self.edit_calls += 1
        self.edit_started.set()
        if self.edit_delay:time.sleep(self.edit_delay)
        if self.edit_block:self.edit_block.wait(15)
        if self.edit_fail:raise WorkError('invalid_report','검증을 위해 발생시킨 보고서 구성 실패')
        result = fixture_plan(units)
        if self.edit_invalid:result['message']['claim_ids']=['NONEXISTENT']
        return result


def fixture_plan(units):
    """Explicit mechanical grouping for tests; never used by the application Engine."""
    sections=[]
    for start in range(0,len(units),12):
        part=units[start:start+12]
        sections.append({'heading':f'검증용 주제 {start//12+1}',
            'overview':{'text':'원문 근거의 주장과 적용 조건을 확인합니다.','claim_ids':[part[0]['id']]},
            'groups':[{'heading':'내용과 관련 조건','entries':[{'claim_id':u['id'],'support_ids':[]} for u in part]}]})
    nodes=[{'key':f'n{i}','label':f'주요 근거 {i+1}','detail':'아래 상세 설명에서 보관 원문과 근거를 확인합니다.',
            'claim_ids':[units[min(i,len(units)-1)]['id']]} for i in range(min(4,max(2,len(units))))]
    return {'title':'검증용 자료 · 에너지와 저장 기술',
        'message':{'text':'검증용 편집 결과입니다. 원문 근거를 묶어 보고서 구성과 출력 동작을 확인합니다.','claim_ids':[units[-1]['id']]},
        'sections':sections,'visual':{'kind':'concept','title':'검증용 개념 구성','nodes':nodes,'edges':[],
        'columns':[],'rows':[],'series':[],'notes':[]}}
