"""Host paths: never share a running Windows service's writable cache with WSL."""
import os
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def is_wsl():
    return platform.system() == 'Linux' and 'microsoft' in platform.release().lower()


def data_directory():
    configured = os.environ.get('PHOTOCLUSTER_DATA_DIR')
    if configured:
        return Path(configured).expanduser().resolve()
    return ROOT / 'data' / 'wsl' if is_wsl() else ROOT / 'data'


DATA = data_directory()
MODEL = Path(os.environ.get('PHOTOCLUSTER_MODEL', str(DATA / 'models/clip-vision-int8.onnx'))).expanduser().resolve()
