"""Report layouts built from validated document and visual structures."""
from __future__ import annotations

import html
import unicodedata

from .config import ASSETS
from .errors import WorkError

BLUE='#2159d6'
INK='#142c49'
MUTED='#5f7188'


def esc(value):
    return html.escape(unicodedata.normalize('NFC',str(value)),quote=True)


def diagram(summary, source, item_id='', local_base='http://127.0.0.1:9417', *, paginate=False):
    from .render import svg_text, evidence_url
    report=summary['report'];visual=report['visual'];body=[];blocks=[]
    block_start=0;block_y=0;context='핵심 주제 한눈에 보기'
    def checkpoint(bottom):
        nonlocal block_start, block_y
        blocks.append((body[block_start:].copy(), block_y, bottom, context))
        block_start=len(body);block_y=bottom
    def text(value,x,y,width,font=28,color=INK,weight=400):
        markup,height=svg_text(unicodedata.normalize('NFC',value),x,y,width/font,font,color,weight)
        body.append(markup);return height
    def rect(x,y,w,h,fill,stroke='none',radius=0):
        body.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}"/>')
    def refs(ids,x,y,width=480):
        # Visible source references remain clickable in SVG/HTML/PDF.
        for index,ref in enumerate(list(dict.fromkeys(ids))[:max(1,min(4,int(width//116)))]):
            link=evidence_url(item_id,source,ref,local_base)
            body.append(f'<a href="{esc(link)}"><text x="{x+index*116}" y="{y}" font-size="20" fill="{BLUE}">[{esc(ref)}]</text></a>')
    text('CHANSUM  /  인포그래픽 요약',64,36,1072,21,BLUE,600)
    y=94
    y+=text(report['title'],64,y,1072,40,INK,700)+12
    start=len(body)
    h=text(report['message']['text'],90,y+40,1020,27,'#fff',500)
    body.insert(start,f'<rect x="64" y="{y}" width="1072" height="{h+40}" rx="10" fill="{BLUE}"/>')
    y+=h+64
    refs(report['message']['sources'],80,y);y+=32
    checkpoint(y)
    if all('digest' in s for s in report['sections']):
        text('핵심 주제 한눈에 보기',64,y,1072,24,INK,700);y+=27
        for index in range(0,len(report['sections']),2):
            start=len(body);panels=[];heights=[]
            for offset,topic in enumerate(report['sections'][index:index+2]):
                x=64+552*offset
                text(f'{index+offset+1:02}',x+22,y+39,52,22,BLUE,700)
                heading_h=text(topic['heading'],x+76,y+39,420,25,INK,700)
                digest_h=text(topic['digest']['text'],x+22,y+heading_h+56,474,24,INK)
                height=heading_h+digest_h+70
                refs(topic['digest']['sources'],x+22,y+height-22,474)
                panels.append((x,height));heights.append(height)
            row_height=max(heights)
            for x,_ in panels:
                body.insert(start,f'<rect x="{x}" y="{y}" width="520" height="{row_height}" rx="8" fill="#f0f5ff"/>')
            y+=row_height+10
            checkpoint(y)
        y+=28
    context=visual['title']
    y+=text(visual['title'],64,y,1072,27,BLUE,700)+4
    kind=visual['kind']
    if kind=='comparison':
        label_w=188;cell_w=(1072-label_w)/len(visual['columns'])
        header_h=max(62,max(len(c)//max(1,int((cell_w-32)/25))+1 for c in visual['columns'])*38+24)
        rect(64,y,1072,header_h,'#edf3ff')
        text('비교 기준',82,y+40,label_w-28,23,MUTED,600)
        for i,label in enumerate(visual['columns']):text(label,int(64+label_w+i*cell_w+18),y+40,cell_w-36,27,BLUE,700)
        y+=header_h
        for row in visual['rows']:
            row_y=y;heights=[text(row['label'],82,y+34,label_w-32,24,INK,600)+36]
            for i,cell in enumerate(row['cells']):
                x=int(64+label_w+i*cell_w+18)
                h=text(cell['text'],x,y+34,cell_w-36,24)
                refs(cell['sources'],x,y+34+h+8,cell_w-36);heights.append(h+59)
            y+=max(heights)+8
            body.append(f'<line x1="64" y1="{y}" x2="1136" y2="{y}" stroke="#cedbea"/>')
            y+=8;checkpoint(y)
        y+=14
    elif kind=='chart':
        maximum=max(d['value'] for d in visual['series']) or 1
        for datum in visual['series']:
            label_h=text(datum['label'],64,y+35,290,26,INK,600)
            rect(376,y+8,600,30,'#eaf0f8',radius=4)
            rect(376,y+8,600*datum['value']/maximum,30,BLUE,radius=4)
            value_h=text(f"{datum['value']:g} {datum['unit']}",376,y+81,760,28,BLUE,600)
            refs_y=y+max(label_h+32,value_h+65)
            refs(datum['sources'],64,refs_y);y=refs_y+36
            checkpoint(y)
        text('축의 시작값 0 · 원문에 명시된 값과 단위',64,y,1072,21,MUTED);y+=54
    elif kind=='flow':
        for index,node in enumerate(visual['nodes']):
            body.append(f'<circle cx="91" cy="{y+17}" r="27" fill="{BLUE}"/>')
            text(str(index+1),83,y+26,40,24,'#fff',600)
            left=text(node['label'],146,y+27,320,29,INK,700)
            right=text(node['detail'],510,y+27,620,27)
            height=max(left,right)+24
            refs(node['sources'],510,y+height);y+=height+16
            if index<len(visual['edges']):
                edge=visual['edges'][index]
                body.append(f'<path d="M91 {y-12} v34" fill="none" stroke="{BLUE}" stroke-width="3" marker-end="url(#arrow)"/>')
                text(edge['label'],146,y+15,930,22,MUTED);y+=42
            checkpoint(y)
    elif kind=='concept' and visual['edges'] and len({e['to_key'] for e in visual['edges']})==1 and len(visual['nodes'])<=4:
        # A grounded convergence relation: actual edges meet the target concept.
        target_key=visual['edges'][0]['to_key']
        nodes={n['key']:n for n in visual['nodes']}
        others=[n for n in visual['nodes'] if n['key']!=target_key]
        heights=[]
        for node in visual['nodes']:
            _,h1=svg_text(node['label'],0,0,360/26,26)
            _,h2=svg_text(node['detail'],0,0,360/24,24)
            heights.append(h1+h2+66)
        box_h=max(heights);gap=22;full_h=len(others)*(box_h+gap)-gap
        positions={n['key']:(64,y+i*(box_h+gap)) for i,n in enumerate(others)}
        positions[target_key]=(720,y+(full_h-box_h)/2)
        for edge in visual['edges']:
            a=positions[edge['from_key']];b=positions[edge['to_key']]
            ay=a[1]+box_h/2;by=b[1]+box_h/2
            body.append(f'<path d="M{a[0]+416} {ay} C590 {ay} 600 {by} {b[0]-10} {by}" stroke="{BLUE}" stroke-width="3" fill="none" marker-end="url(#arrow)"/>')
            text(edge['label'],502,ay-28 if by>=ay else ay+36,190,20,MUTED)
        for key,(x,top) in positions.items():
            node=nodes[key];rect(x,top,416,box_h,'#edf8f7' if key==target_key else '#f1f5fb',radius=10)
            h=text(node['label'],x+24,top+39,366,26,INK,700)
            text(node['detail'],x+24,top+h+54,366,24)
            refs(node['sources'],x+24,top+box_h-21,366)
        y+=full_h+36
        checkpoint(y)
    else:
        for index in range(0,len(visual['nodes']),2):
            row=[]
            for offset,node in enumerate(visual['nodes'][index:index+2]):
                x=64+offset*552
                text(f'{index+offset+1:02}',x,y+25,65,23,BLUE,700)
                h=text(node['label'],x+68,y+25,444,29,INK,700)
                h+=text(node['detail'],x+68,y+32+h,444,26)+22
                refs(node['sources'],x+68,y+40+h);row.append(h+80)
            y+=max(row)+22
            checkpoint(y)
        if visual['edges']:
            y+=text('개념 사이의 관계',64,y,1072,24,BLUE,700)+20
            nodes={n['key']:n for n in visual['nodes']}
            for edge in visual['edges']:
                left=nodes[edge['from_key']]['label'];right=nodes[edge['to_key']]['label']
                h=max(text(left,64,y+28,352,24,INK,600),text(right,784,y+28,352,24,INK,600),
                      text(edge['label'],456,y+14,270,21,MUTED))
                body.append(f'<path d="M446 {y+36} H748" stroke="{BLUE}" stroke-width="2" marker-end="url(#arrow)"/>')
                refs(edge['sources'],456,y+h+44);y+=h+84
                checkpoint(y)
    context='조건 · 유의점'
    for note in visual['notes']:
        y+=8
        text('조건 · 유의점',64,y+24,1072,22,BLUE,700)
        h=text(note['text'],64,y+58,1072,24)
        refs(note['sources'],64,y+67+h);y+=h+82
        checkpoint(y)
    y+=12
    body.append(f'<line x1="64" y1="{y}" x2="1136" y2="{y}" stroke="#cedbea"/>')
    footer=f'원문 {len(source["segments"])}구간 · 주제 {len(report["sections"])}개 · 상세 설명과 근거는 다음 페이지'
    if summary.get('partial'):footer='부분 완료 · 미처리 원문 있음 · '+footer
    if summary.get('verification')=='test-double':footer='검증용 예시 · 실제 AI 요약 아님 · '+footer
    y+=30+text(footer,64,y+30,1072,20,MUTED)
    height=int(y+24)
    checkpoint(height)
    font_uri=(ASSETS/'NotoSansKR.ttf').as_uri()
    katex=(ASSETS/'katex/katex.min.css').read_text(encoding='utf-8').replace('url(fonts/','url('+(ASSETS/'katex/fonts').as_uri()+'/')
    def svg(contents, page_height):
        return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{page_height}" viewBox="0 0 1200 {page_height}" role="img" aria-label="{esc(report['title'])}">
<defs><style>@font-face{{font-family:Noto;src:url('{font_uri}')}}text{{font-family:Noto,sans-serif}}{katex}</style>
<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10" fill="{BLUE}"/></marker></defs>
<rect width="1200" height="{page_height}" fill="white"/>{''.join(contents)}</svg>'''
    if not paginate:
        return svg(body,height)
    # Keep the last diagram element, its caution and footer together. A page
    # containing only a disclaimer/footer is technically valid but unhelpful.
    for tail_count in range(min(3,len(blocks)-1),1,-1):
        tail=blocks[-tail_count:]
        if tail[-1][2]-tail[0][1]<(1000 if tail_count==3 else 1500):
            blocks[-tail_count:]=[(sum((b[0] for b in tail),[]),tail[0][1],tail[-1][2],tail[0][3])]
            break
    # Partition whole semantic blocks, never clip text or shrink its font.
    # At 176 mm wide, a 24 px body font prints at 10 pt; 1710 px fits A4.
    pages=[];contents=[];cursor=0;limit=1710
    for markup,top,bottom,label in blocks:
        block_height=bottom-top
        if contents and cursor+block_height>limit-16:
            pages.append(svg(contents,int(cursor+16)));contents=[];cursor=84
            heading,_=svg_text('CHANSUM / '+label+' · 계속',64,44,1072/21,21,BLUE,600)
            contents.append(heading)
        if cursor+block_height>limit-16:
            raise WorkError('output_layout','하나의 도식 요소가 A4 한 페이지보다 큽니다. 원문의 수식·설명 길이를 확인해 주세요. 기존 결과는 보존됩니다.')
        contents.append(f'<g data-layout-block="true" transform="translate(0 {cursor-top})">'+''.join(markup)+'</g>')
        cursor+=block_height
    if contents:pages.append(svg(contents,int(cursor+16)))
    return pages


def document(item_id,summary,source,svg,local_base):
    from .render import safe_text,evidence_url,external_url
    report=summary['report'];used=set()
    def links(ids):
        used.update(ids)
        return ' '.join(f'<a href="{esc(evidence_url(item_id,source,r,local_base))}">[{esc(r)}]</a>' for r in dict.fromkeys(ids))
    def prose(value,css=''):
        return f'<div class="{css}"><p>{safe_text(value["text"])}</p><div class="refs">{links(value["sources"])}</div></div>'
    labels={'fact':'핵심','argument':'논거','condition':'조건','exception':'예외','formula':'수식'}
    def entry(value,depth=0):
        if 'children' in value:
            result=prose(value['narrative'],'claim') if value.get('narrative') else ''
            result+=''.join(section(s,f'',depth+1) for s in value['children'])
        else:
            item=value['item'];kind=item['kind']
            label=f'<span class="kind">{labels[kind]}</span>' if kind in ('condition','exception','formula') else ''
            result=f'<div class="claim {kind}">{label}{prose(value.get("narrative",item))}</div>'
            if kind in ('condition','exception') and value.get('narrative',{}).get('text',item['text'])!=item['text']:
                result+='<div class="preserved-condition"><span class="kind">보존된 '+labels[kind]+'</span>'+prose(item)+'</div>'
        if value.get('supporting'):
            result+='<div class="supporting">'+''.join(entry(v,depth+1) for v in value['supporting'])+'</div>'
        return result
    def section(value,number,depth=0):
        heading=min(2+depth,5)
        result=f'<section class="topic"><h{heading}>{esc(number)} {esc(value["heading"])}</h{heading}>'+prose(value['overview'],'topic-overview')
        for index,group in enumerate(value['groups'],1):
            sub=f'{number}.{index}' if number else str(index)
            result+=f'<h{min(heading+1,6)}>{esc(sub)} {esc(group["heading"])}</h{min(heading+1,6)}>'
            result+='<ol class="arguments">'+''.join('<li>'+entry(e,depth)+'</li>' for e in group['entries'])+'</ol>'
        return result+'</section>'
    contents=[];chapters=[]
    for i,topic in enumerate(report['sections'],1):
        contents.append(f'<li><a href="#topic-{i}">{i}. {esc(topic["heading"])}</a><ol>'+''.join(f'<li>{i}.{j} {esc(g["heading"])}</li>' for j,g in enumerate(topic['groups'],1))+'</ol></li>')
        chapters.append(f'<div id="topic-{i}">'+section(topic,str(i))+'</div>')
    intro=prose(report['message'],'lead')
    evidence=[]
    for segment in source['segments']:
        if segment['id'] in used:
            text=segment['text']
            # This is explicitly a quotation excerpt; the stored source stays complete.
            excerpt=text if len(text)<=800 else text[:800]+' [이후 내용은 보관 원문에서 확인]'
            evidence.append(f'<div class="evidence"><div class="refs">{links([segment["id"]])}</div><p>{safe_text(excerpt)}</p></div>')
    original=external_url(source.get('url'))
    source_link=f'<a href="{esc(original)}">{esc(original)}</a>' if original else esc(source.get('filename','로컬 파일'))
    notice=''
    if summary.get('verification')=='test-double':notice+='<p class="notice">검증용 AI 테스트 대역의 결과입니다. 실제 AI 요약이 아닙니다.</p>'
    if summary.get('partial'):notice+=f'<p class="notice">부분 완료 · {summary.get("failed_chunks",0)}개 구간 미처리. 제공된 부분에 한정한 정리입니다.</p>'
    covers=''.join('<div class="cover">'+value+'</div>' for value in (svg if isinstance(svg,list) else [svg]))
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{esc(report['title'])}</title>
<link rel="stylesheet" href="{(ASSETS/'katex/katex.min.css').as_uri()}"><style>
@font-face{{font-family:Noto;src:url('{(ASSETS/'NotoSansKR.ttf').as_uri()}')}}
@page{{size:A4;margin:16mm 17mm 19mm}}*{{box-sizing:border-box}}body{{font-family:Noto,sans-serif;color:{INK};font-size:10.5pt;line-height:1.65;margin:0;word-break:keep-all;overflow-wrap:anywhere}}
.cover{{height:257mm;break-after:page;display:flex;align-items:flex-start;justify-content:center}}.cover svg{{max-width:100%;max-height:253mm;width:100%;height:auto}}
h1{{font-size:24pt;line-height:1.5;margin:14pt 0}}h2{{font-size:17pt;border-bottom:1px solid #cdd9e9;padding-bottom:9pt;margin:28pt 0 12pt;color:#194da9}}h3{{font-size:12.5pt;margin:21pt 0 8pt}}h4,h5,h6{{font-size:11.5pt;margin:15pt 0 8pt}}h1,h2,h3,h4,h5,h6{{break-after:avoid}}
p{{margin:3pt 0 7pt}}a{{color:{BLUE};text-decoration:none}}.eyebrow{{letter-spacing:2px;color:{BLUE};font-size:8pt}}.meta,.refs{{font-size:8pt;color:{MUTED}}}.refs a{{display:inline-block;margin-right:5pt}}
.report-intro{{break-after:page}}.lead{{font-size:12pt;line-height:1.85;border-left:3px solid {BLUE};padding:5pt 0 5pt 13pt;margin:24pt 0}}.contents{{padding-left:0;list-style:none}}.contents>li{{margin:13pt 0;break-inside:avoid;font-weight:600}}.contents ol{{font-size:9pt;font-weight:400;color:{MUTED};list-style:none;padding-left:15pt;margin:5pt 0}}
.topic-overview{{color:#3d5675;margin:10pt 0 15pt;font-size:10pt;break-after:avoid}}.arguments{{padding-left:19pt;margin:10pt 0}}.arguments>li{{padding-left:4pt;margin:0 0 12pt;break-inside:avoid}}.claim{{break-inside:avoid}}.kind{{font-size:8pt;font-weight:600;color:{BLUE};display:block;margin-bottom:3pt}}.supporting{{margin:8pt 0 0 3pt;padding:0 0 0 14pt;border-left:2px solid #cedbea}}.supporting .claim{{margin:8pt 0}}.condition .kind{{color:#8b650c}}.exception .kind{{color:#a54445}}
.sources{{break-before:page}}.evidence{{font-size:9pt;border-top:1px solid #e0e6ef;margin-top:8pt;padding-top:5pt;break-inside:avoid}}.notice{{font-size:9pt;border-left:3px solid #b38216;background:#fff8e7;padding:8pt}}.katex{{font-size:1.08em}}.katex-display{{white-space:normal}}.math{{max-width:100%}}
</style></head><body><div class="infographic-pages">{covers}</div><div class="report-intro"><p class="eyebrow">CHANSUM / 상세 리포트</p>
<h1>{esc(report['title'])}</h1><p class="meta">{esc(source['collected_at'][:10])} · {esc(source.get('author') or '작성자 미상')} · 원문 {len(source['segments'])}구간</p>{notice}{intro}
<h2>목차</h2><ol class="contents">{''.join(contents)}</ol></div>{''.join(chapters)}
<section class="sources"><h2>주요 근거와 출처</h2><p>{source_link}</p><p class="meta">수집: {esc(source['collected_at'])}<br>인용은 보관 원문의 일부입니다. 근거 링크에서 전체 문단 또는 유튜브 시점을 확인할 수 있습니다.</p>{''.join(evidence)}</section></body></html>'''
