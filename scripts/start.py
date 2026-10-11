"""Common Windows/Linux launcher. Installs only into an isolated environment."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proxy', default='')
    parser.add_argument('--install-model', action='store_true')
    parser.add_argument('--install-gpu', action='store_true')
    parser.add_argument('--no-install', action='store_true', help='Use existing dependencies without network installation')
    parser.add_argument('--check', action='store_true', help='Check tools and device availability, then exit')
    parser.add_argument('--no-browser', action='store_true', help='Do not open a browser automatically')
    parser.add_argument('--accelerator', choices=['auto', 'cpu'], default='auto')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--adb', help='ADB executable path; accepts Windows adb.exe under WSL')
    parser.add_argument('--data-dir', help='Private cache directory; do not share between running services')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error('Python 3.11+ is required. On Ubuntu 22.04 install a newer Python separately; do not replace system Python.')
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    if args.no_install and args.install_gpu:
        parser.error('--install-gpu cannot be combined with --no-install')
    os.chdir(ROOT)
    env = os.environ.copy()
    env['PHOTOCLUSTER_ACCELERATOR'] = args.accelerator
    if args.adb:
        env['PHOTOCLUSTER_ADB'] = args.adb
    if args.data_dir:
        env['PHOTOCLUSTER_DATA_DIR'] = str(Path(args.data_dir).expanduser().resolve())
    folder = ROOT / ('.venv' if os.name == 'nt' else '.venv-linux')
    python = folder / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    def run(command):
        subprocess.run([str(v) for v in command], check=True, env=env)
    if not python.exists():
        if args.no_install:
            parser.error('Virtual environment missing; run once without --no-install.')
        run([sys.executable, '-m', 'venv', folder])
    if not args.no_install:
        pip = [python, '-m', 'pip', 'install']
        if args.proxy:
            pip += ['--proxy', args.proxy]
        run([*pip, '-r', 'requirements.txt'])
        if args.install_gpu:
            run([*pip, '-r', 'requirements-gpu.txt'])
    if args.install_model:
        run([python, 'scripts/setup_semantic.py', '--proxy', args.proxy])
    run([python, '-c', 'import fastapi, uvicorn, PIL, pillow_heif, numpy, scipy, cv2, onnxruntime, threadpoolctl, psutil'])
    run([python, '-m', 'photocluster.doctor'])
    if args.check:
        return
    print(f'PhotoCluster: http://127.0.0.1:{args.port}', flush=True)
    command = [python, '-m', 'photocluster.server']
    if args.no_browser:
        command.append('--no-browser')
    # Child handles Ctrl+C gracefully; keep its parent alive until cleanup completes.
    import signal
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        run([*command, '--host', '127.0.0.1', '--port', args.port])
    finally:
        signal.signal(signal.SIGINT, previous)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from None
