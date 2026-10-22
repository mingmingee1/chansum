"""Run the real configured adapter on an authored, non-private evaluation case.

Never inject a test engine or copy credentials. No uploaded/user material is used.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from chansum.collect import finalize
from chansum.config import DEFAULT_SETTINGS, Secrets, config_root, write_json
from chansum.engine import Engine, chunk_source, validate_summary
from chansum.errors import WorkError
from chansum.report import build_report
from chansum.render import render_outputs

TEXTS=[
    '이 문서는 가상 학습 프로그램의 내부 검토 예문이다. 실제 연구나 교육 정책 자료가 아니다. 6주 동안 A반 20명과 B반 20명을 관찰했다. 참여자는 희망 반을 선택했으며 무작위 배정하지 않았다.',
    'A반은 주당 3시간의 실시간 수업, B반은 주당 2시간의 녹화 강의를 제공했다. A반은 16명이 수료하여 수료율이 80%였고, B반은 14명이 수료하여 수료율이 70%였다. 수료 기준은 6주 중 5주 이상 과제를 제출하는 것이었다.',
    'A반의 수료율이 높았다는 관찰만으로 실시간 수업의 효과가 더 크다고 결론 내릴 수는 없다. 반 선택 방식과 학습 시간의 차이가 결과에 영향을 주었을 수 있기 때문이다. 또한 시험 점수나 장기적인 학습 효과는 측정하지 않았다.',
    '참가비는 A반 주당 10,000원, B반 주당 8,000원이었다. 이 금액에는 개인의 인터넷 비용과 기기 구입비가 포함되지 않는다. 녹화 강의의 낮은 참가비를 모든 비용의 절감으로 해석해서는 안 된다.',
    '고정된 시간에 참여할 수 있고 즉각적인 질의응답이 필요한 학습자에게는 A반을 제안한다. 일정이 자주 바뀌고 스스로 진도를 관리할 수 있는 학습자에게는 B반을 제안한다. 수료율만으로 반을 일괄 배정하지 않는다.',
    '예외가 있다. 녹화 강의를 선택했더라도 2주 연속으로 과제를 제출하지 못하면 단순히 강의를 추가 제공하지 않고 상담을 먼저 진행한다. 인터넷 이용이 불안정한 학습자에게는 두 반 모두 바로 권하지 않고 오프라인 자료 제공 가능성을 먼저 확인한다.',
    '이 제안은 해당 시범 프로그램과 관찰한 6주에 한정한다. 표본이 작고 시작 시점의 학습 수준도 같지 않으므로 다른 학교나 연령대로 일반화할 근거는 없다. 다음 운영에서는 반 선택 전 학습 수준과 일정 제약을 함께 기록할 계획이다.',
]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=90)
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    source=finalize({'title':'학습 프로그램 선택: 수료율과 적용 조건',
        'filename':'authored-quality-case.txt','author':'Chansum 평가용 가상 예문',
        'segments':[{'id':f'p{i+1:04}','text':text} for i,text in enumerate(TEXTS)]},'file')
    write_json(output/'source.json',source)
    engine=Engine(Secrets(config_root()));config=DEFAULT_SETTINGS|{'timeout':args.timeout}
    config['engine']='codex'
    try:
        results=[]
        chunks=chunk_source(source,config['chunk_chars'])
        for index,segments in enumerate(chunks):
            print(f'Live extraction {index+1}/{len(chunks)}',flush=True)
            results.append(validate_summary(engine.summarize(segments,{'mode':'detail'},config,output/'work'),{s['id'] for s in segments}))
        write_json(output/'extraction.json',results)
        report,hits=build_report(results,source,engine,config,{'mode':'detail'},output/'cache',output,
            lambda stage,done,total:print(f'{stage}: {done}/{total}',flush=True),lambda:None)
        summary={'title':report['title'],'message':report['message']|{'kind':'argument'},'layout':report['visual']['kind'],
            'report':report,'sections':[s for r in results for s in r['sections']], 'verification':'live-engine',
            'partial':False,'failed_chunks':0,'missing_segments':[],'chunk_count':len(chunks),'processed_chunks':len(chunks),
            'engine':'codex','model':'Codex CLI default','options':{'mode':'detail'}}
        render_outputs(output,'authored-live-quality-case',summary,source,'http://127.0.0.1:9417')
        result={'ok':True,'live_engine':True,'cache_hits':hits,'output':str(output)}
    except WorkError as error:
        result={'ok':False,'live_engine':True,'code':error.code,'message':error.message}
    write_json(output/'check.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if result['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
