"""Short-lived disk leases for seekable browser video playback."""
import hashlib
import secrets
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from . import adb


class VideoLeases:
    def __init__(self):
        self.items={};self.lock=threading.Lock();self.slots=threading.BoundedSemaphore(2)
        threading.Thread(target=self.reaper,daemon=True).start()

    def reaper(self):
        while True:
            time.sleep(30)
            with self.lock:tokens=[k for k,v in self.items.items() if v['expires']<time.monotonic()]
            for token in tokens:self.release(token)

    def create(self,serial,photo,expected=None):
        with self.lock:
            if len(self.items)>=4:raise ValueError('请先关闭已有视频查看窗口，再打开更多视频')
        if not self.slots.acquire(False):raise ValueError('已有两个视频正在准备，请稍后重试')
        folder=tempfile.TemporaryDirectory(prefix='photocluster-view-')
        try:
            path=Path(folder.name)/('source'+Path(photo['path']).suffix)
            adb.pull_file(serial,photo['path'],path)
            if path.stat().st_size!=photo['size']:raise ValueError('视频已变化，请同步目录')
            if expected:
                with path.open('rb') as source:
                    if hashlib.file_digest(source,'sha256').hexdigest()!=expected:raise ValueError('视频内容已变化，请重新分类')
            if path.suffix.lower() not in ('.mp4','.webm','.m4v'):
                target=Path(folder.name)/'playback.mp4'
                r=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0','-map','0:a?',
                    '-c','copy','-movflags','+faststart',str(target)],capture_output=True,timeout=180)
                if r.returncode:raise ValueError('该视频无法直接封装为浏览器格式；仍可查看提取的关键帧')
                path=target
            token=secrets.token_urlsafe(32)
            with self.lock:self.items[token]=dict(folder=folder,path=path,expires=time.monotonic()+300)
            return token
        except Exception:
            folder.cleanup();raise
        finally:self.slots.release()

    def get(self,token):
        with self.lock:
            item=self.items.get(token)
            if item:item['expires']=time.monotonic()+300
            return item['path'] if item else None

    def release(self,token):
        with self.lock:item=self.items.get(token)
        if item:
            try:item['folder'].cleanup()
            except (PermissionError,OSError):
                with self.lock:item['expires']=time.monotonic()+30
                return
            with self.lock:self.items.pop(token,None)
