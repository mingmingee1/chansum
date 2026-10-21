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
