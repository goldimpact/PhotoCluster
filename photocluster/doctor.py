"""Read-only environment diagnostics; never print device IDs or media paths."""
import platform
import shutil

from . import adb
from .config import DATA, MODEL, is_wsl


def main():
    print(f'Host: {platform.system()} / {platform.machine()}' + (' (WSL)' if is_wsl() else ''))
    print(f'Python: {platform.python_version()}')
    print(f'ADB: {adb.executable()}')
    print(f'Private cache: {DATA}')
    print('Semantic model: ' + ('installed' if MODEL.is_file() else 'not installed (optional)'))
    for tool in ('ffmpeg', 'ffprobe'):
        print(f'{tool}: ' + ('available' if shutil.which(tool) else 'MISSING; install for video and damaged-media recovery'))
    try:
        devices = adb.devices()
        ready = sum(d['state'] == 'device' for d in devices)
        print(f'Android devices: {ready} ready, {len(devices) - ready} unauthorized/offline')
        if not ready:
            print('Unlock the phone and allow USB debugging. On native Linux check USB/udev permissions; on WSL see docs/LINUX.md.')
    except Exception as exc:
        # Avoid exposing raw ADB diagnostics containing serials in shared reports.
        print(f'ADB check failed ({type(exc).__name__}); verify the executable, USB authorization and server connection.')


if __name__ == '__main__':
    main()
