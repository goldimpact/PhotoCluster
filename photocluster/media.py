"""Bounded keyframe decoding with FFmpeg; damaged media stays visible."""
import hashlib
import io
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


def probe(path):
    r=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
        'stream=width,height,duration,nb_frames:format=duration','-of','json',str(path)],capture_output=True,timeout=30)
    info=json.loads(r.stdout or b'{}');stream=next(iter(info.get('streams',[])),{})
    duration=stream.get('duration') or info.get('format',{}).get('duration') or 0
    try:duration=float(duration)
    except ValueError:duration=0
    return dict(width=int(stream.get('width',0)),height=int(stream.get('height',0)),duration=duration,
                frames=int(stream['nb_frames']) if str(stream.get('nb_frames','')).isdigit() else 0)


def keyframes(path, count=8):
    info=probe(path);frames=[];times=[];warnings=[]
    duration=info['duration']
    positions=np.linspace(0,max(0,duration-.1),count) if duration else [0]
    for position in positions:
        args=['ffmpeg','-v','error','-threads','1','-err_detect','ignore_err']
        if position:args+=['-ss',str(float(position))]
        args+=['-i',str(path),'-an','-frames:v','1','-vf','scale=256:256:force_original_aspect_ratio=decrease,pad=256:256:(ow-iw)/2:(oh-ih)/2:color=white',
               '-threads','1','-f','image2pipe','-vcodec','png','pipe:1']
        try:
            r=subprocess.run(args,capture_output=True,timeout=30)
            if r.stdout:
                with Image.open(io.BytesIO(r.stdout)) as image:
                    frames.append(np.array(image.convert('RGB')));times.append(float(position))
                if r.stderr:warnings.append('解码器报告损坏，已恢复可读画面')
            else:warnings.append(f'{position:.1f} 秒处不可解码')
        except (subprocess.TimeoutExpired,OSError,ValueError):
            warnings.append(f'{position:.1f} 秒处解码未完成')
    if not frames:raise ValueError('无法恢复可读画面；文件仍显示在待检查媒体中')
    return np.stack(frames),times,info,list(dict.fromkeys(warnings))


def file_features(path, thumb_path, sha256=None, video=False, warning=None):
    from .vision import still_features
    frames,times,info,warnings=keyframes(path)
    image=Image.fromarray(frames[0]);buffer=io.BytesIO();image.save(buffer,'PNG')
    result=still_features(buffer.getvalue(),thumb_path)
    frame_path=thumb_path.with_suffix('.frames.npz')
    np.savez_compressed(frame_path,frames=frames,times=np.array(times,np.float32))
    if sha256 is None:
        with Path(path).open('rb') as source:sha256=hashlib.file_digest(source,'sha256').hexdigest()
    result.update(sha256=sha256,media_type='video' if video else 'image',animated=not video,
                  duration_ms=round(info['duration']*1000),frames=info['frames'],sample_count=len(frames),
                  frame_path=str(frame_path),frame_times=times,partial=bool(warnings or warning),
                  warning='；'.join(([warning] if warning else [])+warnings),media_version=2,
                  width=info['width'] or result['width'],height=info['height'] or result['height'])
    return result


def recover_animation(raw,thumb_path,reason):
    # FFmpeg seeks in a unique temporary file; it is removed on success/failure.
    with tempfile.TemporaryDirectory(prefix='photocluster-decode-') as folder:
        path=Path(folder)/'animation.gif';path.write_bytes(raw)
        return file_features(path,thumb_path,hashlib.sha256(raw).hexdigest(),warning='部分/关键帧分析：'+reason)
