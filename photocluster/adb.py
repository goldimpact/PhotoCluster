"""Android MediaStore inventory and read-only image retrieval helpers."""
import re
import shlex
import subprocess
import tarfile
import threading
import os
import shutil
from pathlib import Path

from .config import is_wsl

COLUMNS = ['_id', '_data', '_size', 'date_modified', 'width', 'height', 'bucket_id', 'bucket_display_name', 'datetaken']


def executable():
    # An override is one executable path, never a shell command or argument string.
    configured = os.environ.get('PHOTOCLUSTER_ADB')
    if configured:
        return configured
    return shutil.which('adb') or (shutil.which('adb.exe') if is_wsl() else None) or 'adb'


def local_destination(path):
    if is_wsl() and executable().lower().endswith('.exe'):
        # Windows adb must receive a Windows path, including for Linux /tmp files.
        result = subprocess.run(['wslpath', '-w', str(Path(path).resolve())],
                                capture_output=True, timeout=10, check=True)
        return result.stdout.decode('utf-8').strip()
    return str(path)


def run(args, timeout=120):
    try:
        result = subprocess.run([executable(), *args], capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError('ADB not found. Install Android Platform Tools or set PHOTOCLUSTER_ADB to its executable path.') from None
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace').strip() or 'ADB 命令失败')
    return result.stdout


def devices():
    rows = run(['devices', '-l']).decode('utf-8', 'replace').splitlines()[1:]
    return [{'serial': p[0], 'state': p[1], 'description': ' '.join(p[2:])}
            for row in rows if len(p := row.split()) >= 2]


def parse_inventory(text):
    photos = []
    pattern = re.compile(r'^Row: \d+ _id=(\d+), _data=(.*), _size=(\d+), date_modified=(\d+), width=(\d+|NULL|null), height=(\d+|NULL|null), bucket_id=(.*?), bucket_display_name=(.*?)(?:, datetaken=(\d+|NULL|null))?$')
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.strip() == 'No result found.':
            continue
        m = pattern.match(line)
        if not m:
            raise RuntimeError('无法解析媒体库响应：' + line[:180])
        mid, path, size, modified, width, height, bucket, name, taken = m.groups()
        if not path.startswith('/'):
            raise RuntimeError('媒体库未返回可读取的绝对路径')
        photos.append(dict(media_id=int(mid), path=path, size=int(size), modified=int(modified),
                           width=int(width) if width.isdigit() else 0, height=int(height) if height.isdigit() else 0, album=path.rsplit('/', 1)[0], album_name=name,
                           taken=int(taken)/1000 if taken and taken.isdigit() else 0))
    return photos


def inventory(serial):
    photos=[]
    for kind,collection in [('image','images'),('video','video')]:
        command = f'content query --uri content://media/external/{collection}/media --projection ' + ':'.join(COLUMNS)
        raw = run(['-s', serial, 'shell', command]).decode('utf-8', 'replace')
        photos.extend(dict(p,media_type=kind) for p in parse_inventory(raw))
    return photos


def pull_file(serial, path, destination):
    # A subprocess argument list keeps remote/local names out of shell parsing.
    run(['-s',serial,'pull',path,local_destination(destination)],timeout=1800)


def read_photo(serial, path):
    return run(['-s', serial, 'exec-out', 'cat ' + shlex.quote(path)])


def read_batch(serial, photos, timeout=90):
    """One ADB process for a batch, streamed in RAM with no phone writes.

    On a device without tar, callers fall back to individual reads. Validate
    names and sizes against the inventory; never extract archive paths to disk.
    """
    expected = {p['path'].lstrip('/'): p for p in photos}
    # exec-out merges remote stderr on some Android versions. Use relative
    # archive names to avoid the leading-slash warning corrupting the stream,
    # and discard remote diagnostics; omitted files are retried individually.
    command = 'tar -cf - -C / -- ' + ' '.join(shlex.quote(p['path'].lstrip('/')) for p in photos) + ' 2>/dev/null'
    process = subprocess.Popen([executable(), '-s', serial, 'exec-out', command],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    timer = threading.Timer(timeout, process.kill)
    timer.daemon = True
    timer.start()
    try:
        with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
            for member in archive:
                photo = expected.pop(member.name.lstrip('/'), None)
                if photo is None or not member.isfile():
                    continue
                if member.size != photo['size']:
                    continue
                with archive.extractfile(member) as stream:
                    raw = stream.read()
                if len(raw) != photo['size']:
                    raise RuntimeError('ADB 批量传输中断')
                yield photo, raw
        process.wait(timeout=5)
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()
