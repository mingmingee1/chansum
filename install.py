from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    if not (3,11)<=sys.version_info[:2]<(3,15):
        raise SystemExit('Install Python 3.12 (supported: 3.11-3.14), then run install.bat again.')
    environment = ROOT/'.venv'
    executable = environment/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not executable.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    if subprocess.run([str(executable),'-m','pip','--version'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
        subprocess.run([str(executable),'-m','ensurepip','--upgrade'],check=True)
    subprocess.run([str(executable),'-m','pip','install','--require-hashes','-r',str(ROOT/'requirements.lock.txt')],check=True,cwd=ROOT)
    if not shutil.which('chromium'):
        subprocess.run([str(executable),'-m','playwright','install','chromium'],check=True,cwd=ROOT)
    if os.name=='nt' and not shutil.which('codex') and shutil.which('npm'):
        # Optional adapter; API and Ollama work without Node/Codex.
        print('Install optional Codex CLI for ChatGPT login? (API/Ollama need no Codex.)')
        if input('Type Y to install, or press Enter to skip: ').strip().lower()=='y':
            npm = shutil.which('npm')
            npm_js = Path(npm).parent/'node_modules/npm/bin/npm-cli.js'
            if npm.lower().endswith(('.cmd','.bat')) and not (npm_js.is_file() and shutil.which('node')):
                print('Optional Codex install skipped: install official Node.js, or use API/Ollama in Settings.')
            else:
                command = [shutil.which('node'),str(npm_js)] if npm_js.is_file() and shutil.which('node') else [npm]
                subprocess.run(command+['install','--prefix',str(ROOT/'.tools'),'--save-exact','@openai/codex@0.163.0'],check=True)
    print('\nInstallation complete. Double-click start.bat. Configure the AI engine in Settings.')


if __name__=='__main__':
    main()
