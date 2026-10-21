from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import time
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
import trafilatura
import requests
from youtube_transcript_api import YouTubeTranscriptApi

from .db import now
from .errors import WorkError

MAX_SOURCE = 12 * 1024 * 1024
VIDEO_ID = re.compile(r'^[A-Za-z0-9_-]{11}$')


def normalize_url(raw: str) -> tuple[str, str, str | None]:
    raw = raw.strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise WorkError('invalid_url', 'http 또는 https로 시작하는 올바른 URL을 입력해 주세요.')
    host = parsed.hostname.lower().rstrip('.')
    video = None
    if host in ('youtu.be', 'www.youtu.be'):
        video = parsed.path.strip('/').split('/')[0]
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
        video = parse_qs(parsed.query).get('v', [None])[0]
        if not video and re.match(r'^/(shorts|embed|live)/', parsed.path):
            video = parsed.path.split('/')[2]
    if video:
        if not VIDEO_ID.fullmatch(video):
            raise WorkError('invalid_url', '유튜브 동영상 ID를 확인해 주세요.')
        return 'https://www.youtube.com/watch?v=' + video, 'youtube', video
    query = [(k,v) for k,v in parse_qsl(parsed.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')]
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path or '/', urlencode(sorted(query)), '')), 'web', None


def check_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise WorkError('invalid_url', '허용되지 않는 URL입니다.')
    if parsed.port not in (None,80,443):
        raise WorkError('invalid_url', '웹 수집은 기본 HTTP/HTTPS 포트만 지원합니다.')
    host = parsed.hostname.lower().rstrip('.')
    if host=='localhost' or '.' not in host or host.endswith(('.localhost','.local','.internal','.lan','.home')):
        raise WorkError('private_url','내부 네트워크 주소는 수집하지 않습니다. HTML 파일로 가져와 주세요.')
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal and not literal.is_global:
        raise WorkError('private_url','내부 네트워크 주소는 수집하지 않습니다. HTML 파일로 가져와 주세요.')
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        # CONNECT proxies can provide DNS even when the sandbox has no resolver.
        # Literal/private/local hosts remain rejected above; the configured proxy
        # enforces its own destination policy. Never bypass TLS verification.
        if any(os.environ.get(name) for name in ('HTTPS_PROXY','https_proxy','HTTP_PROXY','http_proxy')):
            return
        raise WorkError('network', '서버 주소를 찾을 수 없습니다. URL과 네트워크를 확인해 주세요.', True)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise WorkError('private_url', '내부 네트워크 주소는 수집하지 않습니다. HTML 파일로 가져와 주세요.')


def fetch_url(url: str, limit=MAX_SOURCE) -> tuple[bytes, str, str]:
    for attempt in range(2):
        try:
            current = url
            with httpx.Client(timeout=httpx.Timeout(25, connect=12), follow_redirects=False,
                              headers={'User-Agent':'Chansum/0.1 (personal reading library)'}) as client:
                for _ in range(6):
                    check_public_url(current)
                    with client.stream('GET', current) as response:
                        if response.status_code in (301,302,303,307,308):
                            current = urljoin(current, response.headers.get('location',''))
                            continue
                        if response.status_code in (401,403,451):
                            raise WorkError('blocked', '사이트가 접근을 차단하거나 로그인을 요구합니다. TXT·HTML 파일로 가져와 주세요.')
                        if response.status_code == 429:
                            raise WorkError('rate_limited', '사이트의 요청 제한입니다. 잠시 후 다시 시도해 주세요.', True)
                        if response.status_code >= 500:
                            raise WorkError('server_error', '원본 서버에 일시적인 오류가 있습니다.', True)
                        if response.status_code >= 400:
                            raise WorkError('http_error', f'원본 서버가 HTTP {response.status_code}을 반환했습니다.')
                        chunks = []
                        count = 0
                        for part in response.iter_bytes():
                            count += len(part)
                            if count > limit:
                                raise WorkError('too_large', '원문이 너무 큽니다. 12MB 이하의 파일로 나누어 가져와 주세요.')
                            chunks.append(part)
                        return b''.join(chunks), current, response.headers.get('content-type','')
                raise WorkError('redirects', '리디렉션이 너무 많습니다.')
        except httpx.TimeoutException:
            error = WorkError('timeout', '수집 시간이 초과되었습니다. 파일로 가져오거나 다시 시도해 주세요.', True)
        except httpx.HTTPError as exc:
            error = (WorkError('blocked','네트워크 정책 또는 사이트가 접근을 차단했습니다. 원문 파일로 가져와 주세요.') if '403' in str(exc) else
                     WorkError('network', '사이트에 연결하지 못했습니다. 네트워크 또는 접근 정책을 확인해 주세요.', True))
        except WorkError as exc:
            error = exc
        if not error.transient or attempt == 1:
            raise error
        time.sleep(1)
    raise AssertionError('unreachable')


def decode_file(data: bytes) -> str:
    for encoding in ('utf-8-sig','cp949'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise WorkError('encoding', 'UTF-8 또는 CP949로 저장된 텍스트 파일을 사용해 주세요.')


def paragraphs(text: str) -> list[dict]:
    blocks = [s.strip() for s in re.split(r'\n\s*\n|\r?\n', text) if s.strip()]
    return [{'id':f'p{i+1:04d}', 'text':s} for i,s in enumerate(blocks)]


def html_source(data: bytes, url: str | None, title: str) -> dict:
    extracted = trafilatura.extract(data, url=url, output_format='json', with_metadata=True,
                                    include_comments=False, include_tables=True, favor_precision=True)
    if not extracted:
        raise WorkError('extraction_failed', '본문을 추출하지 못했습니다. 동적 페이지는 브라우저에서 TXT·HTML로 저장해 가져와 주세요.')
    fields = json.loads(extracted)
    text = fields.get('text','').strip()
    if len(text) < 100:
        raise WorkError('empty_body', '본문이 너무 짧거나 비어 있습니다. 로그인 안내·메뉴만 있는 페이지는 요약하지 않습니다.')
    login = re.search(r'(sign in to continue|log in to (continue|view)|로그인(이|을)?\s*(필요|해|하)|access denied|verify you are human|enable javascript and cookies)', text[:1500], re.I)
    if login and len(text) < 2000:
        raise WorkError('login_required', '로그인 또는 접근 확인 화면이 감지되었습니다. 본문 파일을 가져와 주세요.')
    return {'title':fields.get('title') or title, 'author':fields.get('author'),
            'published_at':fields.get('date'), 'language':fields.get('language'),
            'segments':paragraphs(text), 'url':url,
            'thumbnail_url':urljoin(url,fields['image']) if url and fields.get('image') else None}


def captions(text: str) -> list[dict]:
    pattern = re.compile(r'((?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3})\s*-->\s*((?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3})[^\n]*\n(.*?)(?=\n\s*\n|\Z)', re.S)
    def seconds(value):
        parts = value.replace(',','.').split(':')
        return sum(float(v) * 60**i for i,v in enumerate(reversed(parts)))
    segments = []
    for match in pattern.finditer(text.replace('\r\n','\n')):
        body = html.unescape(re.sub(r'<[^>]+>','',match[3])).strip()
        start, end = seconds(match[1]), seconds(match[2])
        if body and end >= start:
            segments.append({'id':f't{len(segments)+1:04d}', 'text':body, 'start':start, 'duration':end-start})
    if not segments:
        raise WorkError('invalid_captions', '시간 구간이 있는 SRT·VTT 자막을 찾지 못했습니다.')
    return segments


def finalize(source: dict, kind: str) -> dict:
    if not source.get('segments') or sum(len(s['text']) for s in source['segments']) < 20:
        raise WorkError('empty_body', '요약할 본문이 비어 있거나 너무 짧습니다.')
    joined = '\n'.join(s['text'] for s in source['segments'])
    if len(joined)<1500 and re.search(r'(sign in to continue|log in to (continue|view)|로그인(이|을)?\s*(필요|해|하)|access denied|verify you are human)',joined,re.I):
        raise WorkError('login_required','로그인·접근 확인 안내가 감지되었습니다. 실제 본문 파일을 가져와 주세요.')
    source['kind'] = kind
    source['collected_at'] = now()
    source['hash'] = hashlib.sha256(json.dumps(source['segments'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return source


def from_file(path: Path, name: str, url: str | None = None) -> dict:
    data = path.read_bytes()
    extension = Path(name).suffix.lower()
    if extension in ('.html','.htm'):
        source = html_source(data,url,Path(name).stem)
    else:
        text = decode_file(data)
        source = {'title':Path(name).stem, 'url':url, 'author':None, 'published_at':None, 'language':None,
                  'segments':captions(text) if extension in ('.srt','.vtt') else paragraphs(text)}
    source['filename'] = name
    return finalize(source, 'file')


def youtube_source(url: str, video_id: str, fallback: bool) -> dict:
    class TimedSession(requests.Session):
        def request(self,*args,**kwargs):
            kwargs.setdefault('timeout',25)
            return super().request(*args,**kwargs)
    try:
        available = YouTubeTranscriptApi(http_client=TimedSession()).list(video_id)
        choices = list(available)
        preferred = sorted(choices,key=lambda t: (t.language_code not in ('ko','en'), t.is_generated))
        if not preferred:
            raise WorkError('no_transcript','자막이 없습니다. SRT·VTT·TXT 파일을 가져와 주세요.')
        transcript = preferred[0].fetch()
        segments = [{'id':f'y{i+1:04d}','text':s.text,'start':s.start,'duration':s.duration}
                    for i,s in enumerate(transcript) if s.text.strip()]
        language = transcript.language_code
    except WorkError:
        raise
    except Exception as exc:
        name = type(exc).__name__
        if name in ('RequestBlocked','IpBlocked') or 'blocked' in str(exc).lower() or '403' in str(exc):
            raise WorkError('blocked','유튜브가 이 네트워크의 자막 요청을 차단했습니다. 자막 파일을 가져와 주세요.')
        if name in ('TranscriptsDisabled','NoTranscriptFound','VideoUnavailable','VideoUnplayable'):
            if fallback:
                return youtube_fallback(url,video_id)
            raise WorkError('no_transcript','자막이 없거나 사용할 수 없는 영상입니다. 자막 파일을 가져와 주세요.')
        if '429' in str(exc):
            raise WorkError('rate_limited','유튜브 요청 제한입니다. 잠시 후 다시 시도해 주세요.')
        if 'timeout' in name.lower() or 'timed out' in str(exc).lower():
            raise WorkError('timeout','유튜브 자막 수집 시간이 초과되었습니다.',True)
        raise WorkError('transcript_failed','유튜브 자막을 가져오지 못했습니다. 접근 상태를 확인하거나 자막 파일을 가져와 주세요.')
    title, author, published = 'YouTube · ' + video_id, None, None
    try:
        raw,_,_ = fetch_url('https://www.youtube.com/oembed?url='+url+'&format=json',1024*1024)
        metadata = json.loads(raw)
        title, author = metadata.get('title',title), metadata.get('author_name')
    except Exception:
        pass
    return finalize({'title':title,'author':author,'published_at':published,'url':url,
                     'language':language,'segments':segments,'thumbnail_url':f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'},'youtube')


def youtube_fallback(url: str, video_id: str) -> dict:
    import yt_dlp
    class Quiet:
        def debug(self,*a): pass
        def warning(self,*a): pass
        def error(self,*a): pass
    try:
        with yt_dlp.YoutubeDL({'quiet':True,'skip_download':True,'socket_timeout':20,
                              'retries':0,'extractor_retries':0,'logger':Quiet()}) as ydl:
            metadata = ydl.extract_info(url,download=False)
        tracks = metadata.get('subtitles') or metadata.get('automatic_captions') or {}
        languages = sorted(tracks,key=lambda k:k not in ('ko','en'))
        for language in languages:
            track = next((t for t in tracks[language] if t.get('ext')=='vtt'),None)
            if track:
                raw,_,_ = fetch_url(track['url'])
                return finalize({'title':metadata.get('title') or video_id,'url':url,
                                 'author':metadata.get('uploader'),'published_at':metadata.get('upload_date'),
                                 'language':language,'segments':captions(raw.decode('utf-8')),
                                 'thumbnail_url':metadata.get('thumbnail')},'youtube')
    except WorkError:
        raise
    except Exception:
        raise WorkError('no_transcript','보완 수집에서도 자막을 확보하지 못했습니다. 자막 파일을 가져와 주세요.')
    raise WorkError('no_transcript','사용 가능한 자막이 없습니다. SRT·VTT·TXT 파일을 가져와 주세요.')


def from_url(url: str, fallback=True) -> dict:
    normalized, kind, video = normalize_url(url)
    if kind == 'youtube':
        return youtube_source(normalized,video,fallback)
    raw,final_url,mime = fetch_url(normalized)
    if mime and not any(t in mime for t in ('html','text/plain','xhtml')):
        raise WorkError('unsupported_content','웹 본문이 아닙니다. TXT·SRT·VTT·HTML 파일 입력을 이용해 주세요.')
    return finalize(html_source(raw,final_url,urlsplit(final_url).hostname),'web')
