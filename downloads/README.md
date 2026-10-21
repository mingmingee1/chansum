# Windows 다운로드 · 0.2.0

[Chansum-Windows.zip 다운로드](https://github.com/mingmingee1/chansum/blob/codex/chansum-windows/downloads/Chansum-Windows.zip?raw=true)

GitHub의 파일 화면이 열리면 **Download raw file** 버튼으로 받으세요. 비공개 저장소라면 이 저장소에 접근할 수 있는 GitHub 계정으로 로그인해야 합니다.

1. ZIP을 다운로드하고 **전체 압축을 풉니다**. 압축파일 안에서 바로 실행하지 마세요.
2. `Chansum` 폴더를 열고 Python 3.12 설치 후 `install.bat`을 더블클릭합니다. 최초 설치에는 인터넷 연결이 필요합니다.
3. `start.bat`을 더블클릭합니다. 로컬 서버와 브라우저가 열립니다.
4. 브라우저의 **설정 및 백업**에서 요약 엔진을 연결하고 실제 연결 테스트를 진행합니다.

**기존 사용자:** 처리 중인 작업을 마친 뒤 기존 서버 실행 창을 닫으세요. 새 ZIP을 별도 폴더에 풀어 설치·실행하면 `%LOCALAPPDATA%\Chansum\data`의 라이브러리를 그대로 사용합니다. 새 목차·주제별 설명·조건·예외 구조는 자료 상세의 **재생성**으로 적용합니다. 보고서 구성에 추가 AI 호출이 필요하며 열람·다운로드는 저장된 결과를 사용합니다.

## 새 출력 예시

- [5페이지 PDF 다운로드](https://github.com/mingmingee1/chansum/blob/codex/chansum-windows/downloads/Chansum-report-example.pdf?raw=true)
- [인포그래픽 PNG 다운로드](https://github.com/mingmingee1/chansum/blob/codex/chansum-windows/downloads/Chansum-infographic-example.png?raw=true)

가상 예문과 사람이 작성한 구성 계획으로 만든 **출력 검증 예시**입니다. 실제 AI 요약 예시가 아니며 사용자 첨부 자료를 포함하지 않습니다. PDF는 인포그래픽 → 전체 요지·목차 → 주제별 설명과 조건·예외 → 근거 순서입니다. 예시의 근거 링크는 검증용 자료 ID이므로 실제 라이브러리 항목에 연결되지 않습니다.

이 파일은 Python 소스·한글 폰트·화면·설치/실행 스크립트를 묶은 패키지입니다. Python, Chromium, Python 의존성을 사전 설치한 EXE는 아닙니다. 사용자 데이터와 비밀키, 테스트 결과물은 포함하지 않습니다.

패키지 SHA-256은 `Chansum-Windows.sha256`에 기록되어 있습니다. ZIP 내부 무결성 검사와 필수 파일·Windows 배치 파일 줄바꿈 검사를 통과했습니다. Linux에서 자동 테스트 76개, 브라우저 전체 흐름·재시작·별도 위치 백업 복원을 통과했습니다. 실제 Windows PC 실행 및 실제 AI 요약·보고서 구성 품질은 이 클라우드 환경에서 검증하지 못했습니다. [상세 검증 기록](../docs/validation.md)을 참고하세요.
