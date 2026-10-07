"""Start existing test prototype services outside the calling terminal lifetime."""
import json
import shutil
import socket
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / 'work/runtime/highedu-start'


def main():
    LOG.mkdir(parents=True, exist_ok=True)
    python = ROOT / 'code/backend/.venv/Scripts/python.exe'
    node = shutil.which('node.exe')
    if not python.exists() or not node:
        raise RuntimeError('Existing Python virtual environment and Node are required')
    services = [
        ('expert-resources', 8011, ROOT / 'code', [str(python), '-m', 'uvicorn', 'backend.expert_resources.app:app', '--host', '127.0.0.1', '--port', '8011', '--no-access-log']),
        ('metric-verification', 8010, ROOT / 'code', [str(python), '-m', 'uvicorn', 'backend.metric_verification.app:app', '--host', '127.0.0.1', '--port', '8010', '--no-access-log']),
        ('expert-frontend', 3007, ROOT / 'code/frontend', [node, 'node_modules/vite/bin/vite.js', '--mode', 'test']),
    ]
    started = []
    for name, port, cwd, command in services:
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                print(f'{name}: port {port} already occupied; retained, please verify ownership')
                continue
        with (LOG / f'{name}.stdout.log').open('ab') as out, (LOG / f'{name}.stderr.log').open('ab') as err:
            process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        (LOG / f'{name}.json').write_text(json.dumps({'pid': process.pid, 'port': port, 'cwd': str(cwd),
            'mode': 'test', 'startedAt': datetime.now().astimezone().isoformat(), 'launcher': 'independent Windows process'}, ensure_ascii=False), encoding='utf-8')
        started.append((name, port, process))
    for name, port, process in started:
        url = f'http://127.0.0.1:{port}' + ('' if port == 3007 else '/health')
        deadline = time.monotonic() + 40
        while True:
            if process.poll() is not None:
                raise RuntimeError(f'{name} exited; see {LOG}')
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        print(f'{name}: ready {url}', flush=True)
                        break
            except (OSError, TimeoutError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError(f'{name}: readiness timeout')
            time.sleep(1)


if __name__ == '__main__':
    main()
