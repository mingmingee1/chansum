from __future__ import annotations

import html
import json
import os
import re
import shutil
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

from playwright.sync_api import sync_playwright

from .config import ASSETS, write_json
from .errors import WorkError


def wrap(text: str, width: float) -> list[str]:
    lines, line, used = [], '', 0.0
    measure=lambda value:sum(1 if unicodedata.east_asian_width(c) in ('W','F') else .57 for c in value)
    for token in re.findall(r'\S+\s*',text.replace('\n',' ')):
        size=measure(token.rstrip())
        if line and used+size>width:
            lines.append(line.rstrip());line='';used=0
        for char in token:
            units=measure(char)
            if used+units>width and line:
                lines.append(line.rstrip());line='';used=0
            line+=char;used+=units
    if line:
        lines.append(line.rstrip())
    return lines or ['']


def svg_text(text: str, x: int, y: int, width: float, font=28, color='#192942', weight=400):
    if MATH_RE.search(text):
        estimate = MATH_RE.sub('수식 '*6,text)
        height = len(wrap(estimate,width))*round(font*1.55)+font*2
        return (f'<foreignObject x="{x}" y="{y-font}" width="{int(width*font)}" height="{height}">'
                f'<div xmlns="http://www.w3.org/1999/xhtml" style="font-family:Noto,sans-serif;font-size:{font}px;line-height:1.55;color:{color};font-weight:{weight};word-break:keep-all;overflow-wrap:anywhere">{safe_text(text)}</div></foreignObject>'),height
    lines = wrap(text,width)
    parts = [f'<text x="{x}" y="{y}" fill="{color}" font-size="{font}" font-weight="{weight}">']
    for index,line in enumerate(lines):
        parts.append(f'<tspan x="{x}" dy="{0 if index==0 else round(font*1.55)}">{html.escape(line)}</tspan>')
    parts.append('</text>')
    return ''.join(parts), len(lines)*round(font*1.55)


def short(text: str, length: int):
    if len(text)<=length:
        return text
    # Never cut a LaTeX delimiter or fraction in half.
    for match in MATH_RE.finditer(text):
        if match.start()<length<match.end():
            length=match.end()
    return text[:length].rstrip()+('…' if length<len(text) else '')


def infographic(summary: dict, source: dict, item_id: str = '', local_base: str = 'http://127.0.0.1:9417') -> str:
    if summary.get('report'):
        from .design import diagram
        return diagram(summary,source,item_id,local_base)
    body = []
    title, title_h = svg_text(short(summary['title'],70),64,124,24,font=44,weight=700)
    body += ['<text x="64" y="54" fill="#2563eb" font-size="20" letter-spacing="3">CHANSUM / READING NOTES</text>', title]
    y = 124 + title_h + 12
    message, message_h = svg_text(short(summary['message']['text'],190),86,y+52,37,font=29,color='#1849a9',weight=600)
    body.append(f'<rect x="64" y="{y}" width="1072" height="{message_h+86}" rx="12" fill="#edf4ff"/>')
    body.append(message)
    body.append(f'<text x="86" y="{y+message_h+62}" fill="#536b95" font-size="17">{html.escape(" · ".join(summary["message"]["sources"][:4]))}</text>')
    y += message_h+128
    sections = summary['sections'][:4]
    flow = summary['layout']=='flow'
    for index in range(0,len(sections),1 if flow else 2):
        cells = sections[index:index+(1 if flow else 2)]
        row_heights = []
        for offset,section in enumerate(cells):
            x = 64 if flow else 64+offset*552
            width = 1072 if flow else 520
            unit_width = (width-52)/28
            heading, h = svg_text(short(section['heading'],50),x+24,y+42,unit_width,font=27,color='#1d4ed8',weight=700)
            content = [heading]
            current_y = y+42+h+9
            for item in section['items'][:1]:
                text,h = svg_text(short(item['text'],100 if flow else 105),x+24,current_y,unit_width,font=27)
                content.append(text)
                current_y += h+8
                content.append(f'<text x="{x+24}" y="{current_y}" fill="#7a879b" font-size="16">{html.escape(" · ".join(item["sources"][:3]))}</text>')
                current_y += 36
            height = current_y-y+10
            row_heights.append(height)
            body.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="10" fill="#fff" stroke="#d8e1ed" stroke-width="2"/>')
            body += content
        y += max(row_heights)+28
        if flow and index<len(sections)-1:
            body.append(f'<path d="M600 {y-25} v18 m-6 -6 l6 6 6 -6" stroke="#2563eb" fill="none" stroke-width="2"/>')
    footer = f'근거가 연결된 요약 · {len(source["segments"])}개 원문 구간'
    if summary.get('verification')=='test-double':
        footer = '검증용 AI 대역 · 실제 AI 요약 아님 · '+footer
    if len(summary['sections'])>4:
        footer += f' · 전체 {len(summary["sections"])}개 주제 중 4개 (전체 내용은 상세 요약)'
    if summary.get('partial'):
        footer += ' · 부분 완료: 미처리 구간 있음'
    footer_svg,footer_height = svg_text(footer,64,int(y+15),59,font=18,color='#68768c')
    body.append(footer_svg)
    height = int(y+footer_height+50)
    font_uri = (ASSETS/'NotoSansKR.ttf').as_uri()
    katex_css = (ASSETS/'katex/katex.min.css').read_text(encoding='utf-8').replace('url(fonts/','url('+(ASSETS/'katex/fonts').as_uri()+'/')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" role="img" aria-label="{html.escape(summary['title'],quote=True)}">
<defs><style>@font-face{{font-family:Noto;src:url('{font_uri}')}}text{{font-family:Noto,sans-serif}}{katex_css}</style></defs>
<rect width="1200" height="{height}" fill="#ffffff"/>{''.join(body)}</svg>'''


MATH_RE = re.compile(r'\\\((.*?)\\\)|\\\[(.*?)\\\]',re.S)


def safe_text(text: str) -> str:
    text = unicodedata.normalize('NFC',text)
    parts, position = [], 0
    for match in MATH_RE.finditer(text):
        parts.append(html.escape(text[position:match.start()]))
        tex = match.group(1) or match.group(2) or ''
        parts.append(f'<span class="math" data-display="{str(match.group(2) is not None).lower()}" data-tex="{html.escape(tex,quote=True)}"></span>')
        position = match.end()
    parts.append(html.escape(text[position:]))
    return ''.join(parts)


def evidence_url(item_id: str, source: dict, reference: str, local_base: str) -> str:
    segment = next(s for s in source['segments'] if s['id']==reference)
    original = external_url(source.get('url'))
    if source['kind']=='youtube' and original and 'start' in segment:
        return original+'&t='+str(int(segment['start']))+'s'
    return f'{local_base}/#item/{item_id}/source/{reference}'


def external_url(value) -> str | None:
    try:
        parsed=urlsplit(value or '')
        if parsed.scheme in ('http','https') and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return None


def output_html(item_id: str, summary: dict, source: dict, svg: str, local_base: str) -> str:
    if summary.get('report'):
        from .design import document
        return document(item_id,summary,source,svg,local_base)
    sections = []
    labels = {'condition':'조건','exception':'예외','formula':'수식','argument':'논거','fact':'핵심'}
    for section in summary['sections']:
        contents = []
        for item in section['items']:
            references = ' '.join(f'<a href="{html.escape(evidence_url(item_id,source,ref,local_base),quote=True)}">[{html.escape(ref)}]</a>' for ref in item['sources'])
            contents.append(f'<div class="summary-item"><span class="label">{labels[item["kind"]]}</span><p>{safe_text(item["text"])}</p><div class="refs">{references}</div></div>')
        sections.append(f'<section><h2>{html.escape(section["heading"])}</h2>{"".join(contents)}</section>')
    used = {r for section in summary['sections'] for item in section['items'] for r in item['sources']} | set(summary['message']['sources'])
    evidence = []
    for segment in source['segments']:
        if segment['id'] in used:
            link = evidence_url(item_id,source,segment['id'],local_base)
            evidence.append(f'<div class="evidence"><a href="{html.escape(link,quote=True)}">{segment["id"]}</a><p>{safe_text(short(segment["text"],800))}</p></div>')
    original=external_url(source.get('url'))
    source_link = f'<a href="{html.escape(original,quote=True)}">{html.escape(original)}</a>' if original else html.escape(source.get('filename','로컬 파일'))
    font = (ASSETS/'NotoSansKR.ttf').as_uri()
    katex_css = (ASSETS/'katex/katex.min.css').as_uri()
    notice = (f'<p class="warning">부분 완료: {summary.get("failed_chunks",0)}개 분할 구간을 처리하지 못했습니다. 아래는 검증을 통과한 구간의 결과입니다.</p>' if summary.get('partial') else '')
    if summary.get('verification')=='test-double':
        notice += '<p class="warning">검증용 AI 테스트 대역의 결과입니다. 실제 AI 요약이 아닙니다.</p>'
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{html.escape(summary['title'])}</title>
<link rel="stylesheet" href="{katex_css}"><style>
@font-face{{font-family:Noto;src:url('{font}')}}
@page{{size:A4;margin:16mm 17mm 19mm}}*{{box-sizing:border-box}}body{{font-family:Noto,sans-serif;font-size:10.5pt;line-height:1.75;color:#192942;margin:0;overflow-wrap:anywhere}}
.cover{{height:257mm;break-after:page;display:flex;align-items:center;justify-content:center}}.cover svg{{max-width:100%;max-height:253mm;width:auto;height:auto}}
h1{{font-size:23pt;line-height:1.4;color:#153e85}}h2{{font-size:15pt;margin-top:23pt;break-after:avoid;color:#1d4ed8}}p{{margin:5pt 0 9pt}}
a{{color:#1d4ed8;text-decoration:none}}.summary-item{{break-inside:avoid;margin:12pt 0 17pt}}.label{{font-size:9pt;color:#64748b}}
.refs{{font-size:8.5pt}}.evidence{{break-inside:avoid;margin:8pt 0 9pt;padding-top:6pt;border-top:1px solid #dce4ef;font-size:9pt;line-height:1.65;color:#445268}}.meta{{font-size:9pt;color:#64748b}}.warning{{border-left:3px solid #d49213;padding:8pt;background:#fff8e7}}
.katex{{font-size:1.08em}}.katex-display{{white-space:normal}}.math{{max-width:100%}}
</style></head><body><div class="cover">{svg}</div><h1>{html.escape(summary['title'])}</h1>
<p class="meta">Chansum · {html.escape(source['collected_at'][:10])} · {html.escape(str(source.get('author') or '작성자 미상'))}</p>
{notice}<p>{safe_text(summary['message']['text'])}</p>{''.join(sections)}
<section><h2>주요 근거와 출처</h2><p class="meta">{source_link}<br>수집: {html.escape(source['collected_at'])}<br>근거 링크는 유튜브 시점 또는 로컬 라이브러리의 보관 문단을 엽니다.</p>{''.join(evidence)}</section>
</body></html>'''


def browser_options() -> dict:
    executable = os.environ.get('CHANSUM_CHROMIUM') or shutil.which('chromium')
    return {'executable_path':executable} if executable else {}


def svg_sheet(pages):
    """One editable SVG and PNG can contain all paginated infographic panels."""
    if len(pages)==1:return pages[0]
    elements=[];top=0
    for value in pages:
        height=int(re.search(r'<svg[^>]* height="(\d+)"',value)[1])
        elements.append(value.replace('<svg ',f'<svg x="0" y="{top}" ',1))
        top+=height+24
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{top-24}" viewBox="0 0 1200 {top-24}"><rect width="1200" height="100%" fill="white"/>'+''.join(elements)+'</svg>'


def render_outputs(folder: Path, item_id: str, summary: dict, source: dict, local_base: str):
    folder.mkdir(parents=True,exist_ok=True)
    write_json(folder/'summary.json',summary)
    if summary.get('report'):
        from .design import diagram
        pages=diagram(summary,source,item_id,local_base,paginate=True)
    else:
        pages=[infographic(summary,source,item_id,local_base)]
    svg=svg_sheet(pages)
    (folder/'infographic.svg').write_text(svg,encoding='utf-8')
    document = output_html(item_id,summary,source,pages if summary.get('report') else svg,local_base)
    if not summary.get('report'):
        document=document.replace('<div class="cover">'+svg+'</div>','<div class="infographic-pages"><div class="cover">'+svg+'</div></div>')
    (folder/'report.html').write_text(document,encoding='utf-8')
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            try:
                page = browser.new_page(viewport={'width':1280,'height':1000},device_scale_factor=1)
                # Exports must be self-contained. Never follow a remote URL embedded
                # in source material while rendering.
                render_base = 'http://127.0.0.1:9417/_chansum_render'
                render_document = document.replace(ASSETS.as_uri(),render_base+'/assets')
                def local_resource(route):
                    url = route.request.url
                    if url==render_base+'/report.html':
                        route.fulfill(body=render_document,content_type='text/html; charset=utf-8')
                    elif url.startswith(render_base+'/assets/'):
                        relative = unquote(urlsplit(url).path.split('/assets/',1)[1])
                        asset = (ASSETS/relative).resolve()
                        if asset.is_relative_to(ASSETS.resolve()) and asset.is_file():
                            route.fulfill(path=asset)
                        else:
                            route.abort()
                    else:
                        route.abort()
                page.route('**/*',local_resource)
                page.goto(render_base+'/report.html',wait_until='load')
                page.add_script_tag(path=str(ASSETS/'katex/katex.min.js'))
                errors = page.evaluate('''() => {
                    const errors=[];
                    document.querySelectorAll('.math').forEach(el=>{
                      try { katex.render(el.dataset.tex,el,{displayMode:el.dataset.display==='true',throwOnError:true,trust:false,maxExpand:1000,maxSize:10}); }
                      catch(e) { errors.push(el.dataset.tex); }
                    });
                    return errors;
                }''')
                if errors:
                    raise WorkError('math_render','수식을 조판하지 못했습니다. 기존 결과는 보존됩니다. 원문 수식과 AI 출력을 확인해 주세요.')
                page.evaluate('document.fonts.ready')
                layout = page.evaluate('''() => [...document.querySelectorAll('.cover svg')].map(svg=>{
                    const boundary=svg.getBoundingClientRect();
                    const boxes=[...svg.querySelectorAll('text'), ...[...svg.querySelectorAll('foreignObject')].map(node=>node.firstElementChild)].map(node=>node.getBoundingClientRect());
                    const outside=boxes.some(r=>r.left<boundary.left-1 || r.top<boundary.top-1 || r.right>boundary.right+1 || r.bottom>boundary.bottom+1);
                    const mathOverflow=[...svg.querySelectorAll('foreignObject')].some(node=>{
                      const child=node.firstElementChild;return child.scrollWidth>node.width.baseVal.value+2 || child.scrollHeight>node.height.baseVal.value+2;
                    });
                    let overlaps=0;
                    boxes.forEach((a,i)=>boxes.slice(i+1).forEach(b=>{
                      if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>2 && Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>2)overlaps++;
                    }));
                    return {height:svg.viewBox.baseVal.height,outside,mathOverflow,overlaps};
                })''')
                write_json(folder/'layout-check.json',{'pages':layout})
                if any(p['outside'] or p['mathOverflow'] or p['overlaps'] for p in layout):
                    raise WorkError('output_layout','인포그래픽에 겹치거나 배치 범위를 넘는 글자·수식이 있습니다. 기존 결과는 보존됩니다.')
                page.locator('script').evaluate_all('(nodes)=>nodes.forEach(node=>node.remove())')
                # Persist the already-typeset, editable originals as well as the
                # raster/PDF; opening an HTML original needs no AI or script.
                typed_pages=page.locator('.cover svg').evaluate_all('(nodes)=>nodes.map(node=>node.outerHTML)')
                (folder/'infographic.svg').write_text(svg_sheet(typed_pages).replace(render_base+'/assets',ASSETS.as_uri()),encoding='utf-8')
                (folder/'report.html').write_text(page.content().replace(render_base+'/assets',ASSETS.as_uri()),encoding='utf-8')
                page.evaluate("document.querySelector('.infographic-pages').style.cssText='width:1200px;background:white';document.querySelectorAll('.cover').forEach(node=>node.style.cssText='height:auto;display:block;margin:0 0 24px');document.querySelectorAll('.cover svg').forEach(svg=>svg.style.cssText='max-width:none;max-height:none;width:1200px;height:auto;display:block');")
                page.locator('.infographic-pages').screenshot(path=str(folder/'infographic.png'),scale='css')
                page.evaluate("document.querySelector('.infographic-pages').removeAttribute('style');document.querySelectorAll('.cover,.cover svg').forEach(node=>node.removeAttribute('style'));")
                page.set_viewport_size({'width':665,'height':1000})
                if page.evaluate('''() => [...document.querySelectorAll('.summary-item .katex,.claim .katex,.evidence .katex,.lead .katex,.topic-overview .katex')].some(node=>node.getBoundingClientRect().width>node.closest('.summary-item,.claim,.evidence,.lead,.topic-overview').clientWidth+2)'''):
                    raise WorkError('output_layout','수식이 A4 본문 폭을 넘었습니다. 분할 한도나 정리 옵션을 줄여 재생성해 주세요. 기존 결과는 보존됩니다.')
                page.pdf(path=str(folder/'report.pdf'),format='A4',print_background=True,prefer_css_page_size=True,
                         display_header_footer=True,header_template='<span></span>',
                         footer_template='<div style="width:100%;text-align:center;font-size:8px;color:#64748b">Chansum · <span class="pageNumber"></span> / <span class="totalPages"></span></div>')
            finally:
                browser.close()
    except WorkError:
        raise
    except Exception:
        raise WorkError('output_failed','PNG·PDF 생성에 실패했습니다. Chromium 설치와 데이터 폴더 권한을 확인해 주세요. 기존 성공 결과는 보존됩니다.')
