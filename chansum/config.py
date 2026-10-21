from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"


def home_root() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Chansum"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "chansum"


def data_root() -> Path:
    return Path(os.environ.get("CHANSUM_DATA_DIR", home_root() / "data")).expanduser().resolve()


def config_root() -> Path:
    return Path(os.environ.get("CHANSUM_CONFIG_DIR", home_root() / "config")).expanduser().resolve()


def codex_command() -> str | None:
    local = ROOT / ".tools/node_modules/.bin" / ("codex.cmd" if os.name == "nt" else "codex")
    return str(local) if local.exists() else shutil.which("codex")


def codex_arguments(*arguments: str) -> list[str]:
    executable = codex_command()
    if not executable:
        return []
    # npm's Windows shim is a batch file. Invoke its JavaScript entry point
    # through Node directly so model/path arguments never enter cmd.exe.
    if executable.lower().endswith(('.cmd','.bat')):
        node = shutil.which('node')
        candidates = [ROOT/'.tools/node_modules/@openai/codex/bin/codex.js',
                      Path(executable).parent/'node_modules/@openai/codex/bin/codex.js']
        for script in candidates:
            if node and script.is_file():
                return [node,str(script),*arguments]
        raise OSError('공식 Codex CLI의 Node 실행 파일을 찾지 못했습니다. Node.js와 Codex를 다시 설치해 주세요.')
    return [executable,*arguments]


DEFAULT_SETTINGS = {
    "engine": "codex", "model": "", "base_url": "https://api.openai.com/v1",
    "chunk_chars": 12000, "timeout": 180, "youtube_fallback": True,
}


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class Secrets:
    """Kept outside the backed-up data tree; never returned by an API."""

    def __init__(self, root: Path):
        self.path = root / "credentials.json"

    @staticmethod
    def origin(url: str) -> str:
        parsed=urlsplit(url)
        port=parsed.port or (443 if parsed.scheme=='https' else 80)
        return f'{parsed.scheme}://{parsed.hostname}:{port}'

    def get(self, base_url: str | None = None) -> str:
        requested=self.origin(base_url) if base_url else None
        if os.environ.get("CHANSUM_API_KEY"):
            allowed=self.origin(os.environ.get('CHANSUM_API_KEY_ORIGIN','https://api.openai.com'))
            if requested is None or requested==allowed:
                return os.environ['CHANSUM_API_KEY']
        if self.path.exists():
            saved=json.loads(self.path.read_text(encoding='utf-8'))
            allowed=saved.get('origin',self.origin('https://api.openai.com'))
            return saved.get('api_key','') if requested is None or requested==allowed else ''
        return ""

    def set(self, value: str, base_url: str = 'https://api.openai.com') -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        descriptor = os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
            json.dump({'api_key':value,'origin':self.origin(base_url)},stream)
        temporary.chmod(0o600)
        temporary.replace(self.path)
