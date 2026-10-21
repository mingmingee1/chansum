"""Curated fictional input and report plans for visual QA. No live AI claims."""
import copy
import json
from pathlib import Path

from chansum.collect import finalize
from chansum.report import evidence_units, materialize, validate_plan


TEXTS=[
('fact',r'전력은 에너지를 사용하는 빠르기이며 단위는 W다. 에너지의 단위는 J다. 전력이 일정할 때 에너지는 \(E=Pt\)로 계산한다.'),
('fact','장치 A의 정격 전력은 100 W다. 이 전력으로 10 s 동안 작동하면 사용하는 에너지는 1,000 J다.'),
('fact','장치 B의 정격 전력은 60 W다. 이 전력으로 10 s 동안 작동하면 사용하는 에너지는 600 J다.'),
('condition','두 장치의 에너지 사용량은 같은 작동 시간과 운전 조건에서 비교해야 한다. 정격 전력이 유지된다는 가정이 필요하다.'),
('exception','기동 순간이나 운전 모드가 바뀔 때는 실제 전력이 정격 전력과 다를 수 있다. 이런 구간은 별도로 측정한다.'),
('argument','이 예시에서 같은 10 s 동안 작동한 장치 B는 A보다 에너지를 적게 사용한다. 전력만으로는 작동 시간이 다른 두 장치의 총 에너지를 비교할 수 없다.'),
('fact','배터리에 표시된 저장 에너지와 실제로 꺼내 쓸 수 있는 에너지는 다를 수 있다. 변환 과정과 사용 환경을 함께 확인한다.'),
('condition','변환 효율이나 실제 사용 가능량이 주어지지 않았다면 임의의 효율 또는 손실 비율을 가정하지 않는다.'),
('fact','사용량을 계산할 때는 먼저 전력을 확인하고, 다음으로 작동 시간을 확인한다. 두 값의 단위를 맞춰 에너지를 계산한 뒤 같은 조건의 결과와 비교한다.'),
('fact',r'운동 에너지는 \(E_k=\frac{1}{2}mv^2\)로 나타낸다. 질량을 kg, 속력을 m/s로 넣으면 운동 에너지의 단위는 J다.'),
('exception','속력이 변하는 운동의 에너지는 각 시점의 속력으로 계산해야 한다. 한 시점의 값을 전체 운동에 그대로 적용하지 않는다.'),
]


def bundle(kind='comparison'):
    source=finalize({'title':'전력과 에너지, 같은 기준으로 비교하기','author':'Chansum 검증용 작성 예문',
        'filename':'전력과 에너지 검증 예문.txt','language':'ko','segments':[{'id':f'p{i+1:04}','text':t} for i,(_,t) in enumerate(TEXTS)]},'file')
    items=[{'kind':k,'text':t,'sources':[f'p{i+1:04}']} for i,(k,t) in enumerate(TEXTS)]
    extraction=[{'title':source['title'],'message':items[0],'layout':'comparison','sections':[{'heading':'추출 근거','items':items}]}]
    units=evidence_units(extraction,source)
    c=lambda i:units[i-1]['id']
    ref=lambda text,*ids:{'text':text,'claim_ids':[c(i) for i in ids]}
    entry=lambda i,*support:{'claim_id':c(i),'support_ids':[c(j) for j in support]}
    topic=lambda heading,overview,group,entries:{'heading':heading,'overview':overview,'groups':[{'heading':group,'entries':entries}]}
    plan={'title':source['title'],
        'message':ref('에너지 사용량은 전력과 작동 시간을 함께 봐야 합니다. 같은 10 s 동안 정격 전력을 유지하는 예시에서 장치 A는 1,000 J, B는 600 J를 사용합니다.',2,3,4,6),
        'sections':[
            topic('전력과 에너지를 구분하기',ref('전력은 사용 속도, 에너지는 사용한 양입니다. 계산에는 단위와 적용 조건이 함께 필요합니다.',1),'단위와 계산식',[entry(1)]),
            topic('두 장치를 같은 조건에서 비교하기',ref('같은 시간과 운전 조건을 먼저 맞춘 뒤, 각 장치가 사용한 에너지를 비교합니다.',2,3,4),'비교 결과와 적용 범위',[entry(2,4,5),entry(3),entry(6)]),
            topic('표시된 값과 실제 사용량 해석하기',ref('저장 에너지와 실제 사용 가능량을 구분하고, 없는 효율 수치를 채워 넣지 않습니다.',7,8),'확인할 정보와 계산 순서',[entry(7,8),entry(9)]),
            topic('수식의 조건과 시점 확인하기',ref('운동 에너지 계산은 해당 시점의 질량과 속력을 사용하며, 결과의 단위를 확인합니다.',10,11),'운동 에너지의 적용',[entry(10,11)])]}
    visual={'kind':kind,'title':'장치 A와 B의 전력·에너지 비교','nodes':[],'edges':[],'columns':[],'rows':[],'series':[],
        'notes':[ref('동일한 10 s와 정격 전력 유지가 전제입니다. 기동·모드 변경 구간의 전력은 별도로 확인합니다.',4,5)]}
    if kind=='comparison':
        visual['columns']=['장치 A','장치 B']
        visual['rows']=[{'label':label,'cells':[ref(a,*ai),ref(b,*bi)]} for label,a,ai,b,bi in [
            ('정격 전력','100 W',(2,),'60 W',(3,)),('작동 시간','10 s',(2,),'10 s',(3,)),
            ('사용 에너지','1,000 J',(2,),'600 J',(3,)),('해석','같은 시간의 사용량을 비교',(4,6),'이 예시에서는 더 적은 에너지 사용',(3,6))]]
    elif kind=='chart':
        visual['title']='원문에 명시된 정격 전력'
        visual['series']=[{'label':'장치 A','value':100,'unit':'W','quote':'정격 전력은 100 W','claim_ids':[c(2)]},
                          {'label':'장치 B','value':60,'unit':'W','quote':'정격 전력은 60 W','claim_ids':[c(3)]}]
    elif kind=='flow':
        visual['title']='에너지 사용량을 비교하는 순서'
        visual['nodes']=[{'key':f'n{i}','label':label,'detail':detail,'claim_ids':[c(9)]} for i,(label,detail) in enumerate([
            ('전력 확인','해당 운전 상태의 전력을 확인합니다.'),('작동 시간 확인','전력이 유지된 작동 시간을 확인합니다.'),
            ('에너지 계산','전력과 시간의 단위를 맞춰 계산합니다.'),('같은 조건에서 비교','운전 조건과 작동 시간이 같은 결과를 비교합니다.')])]
        visual['edges']=[{'from_key':f'n{i}','to_key':f'n{i+1}','label':label,'claim_ids':[c(9)]} for i,label in enumerate(['다음으로','단위를 맞춘 뒤','계산 결과 확인'])]
    else:
        visual['title']='사용 속도·시간·에너지의 관계'
        visual['nodes']=[{'key':key,'label':label,'detail':detail,'claim_ids':[c(1),c(9)]} for key,label,detail in [
            ('power','전력 P','에너지를 사용하는 빠르기입니다. 단위는 W입니다.'),
            ('time','작동 시간 t','전력이 유지된 시간입니다. 계산 전에 단위를 맞춥니다.'),
            ('energy','에너지 E','전력이 일정할 때 전력과 작동 시간의 곱으로 계산합니다.')]]
        visual['edges']=[{'from_key':key,'to_key':'energy','label':'계산에 함께 사용','claim_ids':[c(1),c(9)]} for key in ['power','time']]
    plan['visual']=visual
    report=materialize(validate_plan(plan,units,source),units)
    report.update(claim_count=len(units),editing_passes=1)
    summary={'title':report['title'],'message':report['message']|{'kind':'argument'},'layout':kind,'report':report,
        'sections':extraction[0]['sections'],'partial':False,'failed_chunks':0,'chunk_count':1,'processed_chunks':1,
        'missing_segments':[],'verification':'test-double','engine':'test-double','model':'curated-visual-fixture',
        'prompt_version':'curated-example-2','source_hash':source['hash'],'options':{'mode':'detail'}}
    return source,summary


def render_examples():
    import fitz
    from chansum.render import render_outputs
    root=Path(__file__).resolve().parents[1]/'test-results'/'report-v2'
    for kind in ['comparison','concept','flow','chart']:
        source,summary=bundle(kind);folder=root/kind
        render_outputs(folder,'visual-example',summary,source,'http://127.0.0.1:9417')
        doc=fitz.open(folder/'report.pdf')
        for previous in folder.glob('page-*.png'):previous.unlink()
        for index,page in enumerate(doc):
            page.get_pixmap(matrix=fitz.Matrix(1.15,1.15)).save(folder/f'page-{index+1}.png')
            for box in page.get_text('blocks'):
                assert box[0]>=0 and box[1]>=0 and box[2]<=page.rect.width+.5 and box[3]<=page.rect.height+.5,(kind,index,box)
        assert doc[0].get_links(),kind+' cover references are not clickable'
        text=''.join(p.get_text() for p in doc)
        assert '목차' in text and '조건' in text and '예외' in text and '1,000' in text and '600' in text
        print(kind,'pages',len(doc),'cover links',len(doc[0].get_links()),'all pages rendered')


if __name__=='__main__':render_examples()
