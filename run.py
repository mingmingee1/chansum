"""Double-click entry point; one server per data directory, loopback only."""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from chansum.config import data_root, write_json


def probe(port: int, expected: Path) -> bool:
    try:
        # Loopback must never go through a corporate HTTP proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/api/health',timeout=1) as response:
            value = json.load(response)
        return value.get('app')=='chansum' and Path(value.get('data_dir','')).resolve()==expected
    except (OSError,ValueError):
        return False


def acquire_lock(path: Path):
    handle = path.open('a+b')
    if not path.stat().st_size:
        handle.write(b'0'); handle.flush()
    handle.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def main() -> int:
    parser = argparse.ArgumentParser(description='Start Chansum on this computer')
    parser.add_argument('--port',type=int,default=int(os.environ.get('CHANSUM_PORT','9417')))
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--no-browser',action='store_true')
    args = parser.parse_args()
    if not 1024<=args.port<=65535:
        parser.error('port must be between 1024 and 65535')
    if args.data_dir:
        os.environ['CHANSUM_DATA_DIR'] = str(args.data_dir.resolve())
    root = data_root()
    root.mkdir(parents=True,exist_ok=True)
    server_file = root/'server.json'
    candidates = [args.port]
    if server_file.exists():
        try:
            candidates.insert(0,int(json.loads(server_file.read_text())['port']))
        except (ValueError,KeyError,OSError):
            pass
    def open_existing():
        for port in candidates:
            if probe(port,root):
                print(f'Using existing Chansum server on port {port}.')
                if not args.no_browser:
                    webbrowser.open(f'http://127.0.0.1:{port}')
                return True
        return False
    if open_existing():
        return 0
    lock = acquire_lock(root/'.server.lock')
    if not lock:
        for _ in range(20):
            time.sleep(.4)
            if open_existing():
                return 0
        print('Another Chansum process is starting or stopping. Try again shortly.')
        return 1
    os.environ['CHANSUM_PORT'] = str(args.port)
    write_json(server_file,{'port':args.port,'pid':os.getpid()})
    if not args.no_browser:
        def open_when_ready():
            for _ in range(100):
                if probe(args.port,root):
                    webbrowser.open(f'http://127.0.0.1:{args.port}')
                    return
                time.sleep(.2)
        threading.Thread(target=open_when_ready,daemon=True).start()
    try:
        import uvicorn
        from chansum.app import create_app
        print('Chansum data: '+str(root))
        print('Close this window or press Ctrl+C to stop the local server.')
        uvicorn.run(create_app(),host='127.0.0.1',port=args.port,access_log=False)
        return 0
    finally:
        lock.close()


if __name__=='__main__':
    raise SystemExit(main())
