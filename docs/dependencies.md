# 의존성 확인 (2026-10-20)

Python 3.12.14에서 설치·실행했습니다. 앱 요구 버전은 Python 3.11~3.14입니다. 공식 PyPI 메타데이터의 `requires_python` 및 현재 사용 예제를 확인하고 아래 버전으로 고정했습니다. 문서 웹사이트 일부는 네트워크에서 차단되어 공식 GitHub 소스의 문서를 확인했습니다.

| 라이브러리 | 버전 | 사용 및 공식 자료 |
| --- | --- | --- |
| FastAPI | 0.153.0 | 파일 업로드·동기 처리·수명주기. [공식 업로드 문서 소스](https://github.com/fastapi/fastapi/blob/master/docs/en/docs/tutorial/request-files.md) |
| Uvicorn | 0.54.0 | 단일 로컬 서버. [PyPI](https://pypi.org/project/uvicorn/0.54.0/) |
| httpx | 0.28.1 | 제한 시간·수동 리디렉션·프록시 지원 HTTP. [공식 문서](https://www.python-httpx.org/) |
| python-multipart | 0.0.32 | 브라우저 파일 입력. [PyPI](https://pypi.org/project/python-multipart/0.0.32/) |
| Trafilatura | 2.3.1 | `extract(..., output_format='json', with_metadata=True)`. [공식 Python 사용 문서 소스](https://github.com/adbar/trafilatura/blob/master/docs/usage-python.rst) |
| youtube-transcript-api | 1.2.4 | 객체 API의 `list`, `fetch`, `language_code`, `start`, `duration`, 사용자 HTTP 세션. [공식 README](https://github.com/jdepoix/youtube-transcript-api) |
| yt-dlp | 2026.8.19 | 메타데이터·VTT 보완, 영상 다운로드 제외. [공식 저장소](https://github.com/yt-dlp/yt-dlp) |
| Playwright | 1.64.0 | 출력/검증용 Chromium. [공식 Python 저장소](https://github.com/microsoft/playwright-python) |
| Codex CLI (선택) | 0.163.0 | 기존 ChatGPT 인증 사용. `exec --ephemeral --output-schema` 등 설치된 CLI 도움말 및 [공식 설정 스키마](https://github.com/openai/codex/blob/main/codex-rs/core/config.schema.json) 확인 |
| KaTeX (포함 자산) | 0.16.25 | 안전한 수식 조판. npm tarball의 SHA-512 `dist.integrity`를 검증한 뒤 JS/CSS/폰트 보관. [공식 저장소](https://github.com/KaTeX/KaTeX) |
| Noto Sans KR (포함 자산) | Google Fonts의 가변 TTF | [공식 배포](https://github.com/google/fonts/tree/main/ofl/notosanskr), OFL 포함. SHA-256: `194018e6b2b293a7964f037b25c0249ce1418bc9ab3c971060a03aa57861e252` |

개발 검증: pytest 9.1.1, PyMuPDF 1.26.6, Pillow 12.3.0. 전이 의존성·플랫폼별 패키지·아티팩트 해시는 `uv.lock`, `requirements.lock.txt`에 있습니다. 앱은 PDF 생성을 위해 ReportLab·WeasyPrint·외부 CDN을 요구하지 않습니다. Windows의 Playwright 브라우저 다운로드는 공식 설치 명령이 수행합니다. 이 Linux 환경에서는 설치되어 있던 시스템 Chromium으로 실제 렌더링했습니다.

TLS, 패키지 서명/해시 검증을 비활성화하지 않았습니다. 인증 키·값은 이 문서나 잠금 파일에 기록하지 않습니다.
