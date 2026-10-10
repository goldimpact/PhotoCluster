import hashlib
import io
import base64
import os
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageOps
from scipy.fft import dctn
from pillow_heif import register_heif_opener

register_heif_opener()
cv2.setNumThreads(1)
PROJECTION = np.random.default_rng(20261010).normal(size=(128, 64)).astype(np.float32)


def descriptor_signatures(descriptors):
    if descriptors is None or not len(descriptors):
        return []
    root = np.sqrt(descriptors / np.maximum(descriptors.sum(axis=1, keepdims=True), 1e-9))
    root -= root.mean(axis=1, keepdims=True)
    packed = np.packbits(root @ PROJECTION > 0, axis=1)
    return [int.from_bytes(row.tobytes(), 'big') for row in packed]


def phash(rgb):
    gray = cv2.cvtColor(cv2.resize(rgb, (32, 32), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2GRAY)
    freq = dctn(gray.astype(float), norm='ortho')[:8, :8].flatten()
    bits = freq > np.median(freq[1:])
    bits[0] = False
    return int.from_bytes(np.packbits(bits).tobytes(), 'big')


def encode_array(a):
    return base64.b64encode(a.tobytes()).decode('ascii')


def features(raw, thumb_path):
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if getattr(source, 'is_animated', False):
                return animation_features(raw, source, thumb_path)
        return still_features(raw, thumb_path)
    except (ValueError,OSError,EOFError) as exc:
        from .media import recover_animation
        return recover_animation(raw,thumb_path,str(exc))


def animation_features(raw, source, thumb_path):
    """Compare a timeline, never classify an animation by its cover alone.

    Sequential seek lets Pillow composite GIF disposal/transparency correctly.
    Store at most 12 timeline samples; reject over-budget files explicitly.
    """
    frames, durations = [], []
    width, height = source.size
    first = None
    index = 0
    while True:
        try:
            source.seek(index)
        except EOFError:
            break
        if index >= 1200 or (index+1)*width*height > 300_000_000:
            raise ValueError('动画超过分析上限（1200 帧或 3 亿解码像素），仍可查看原图')
        rgba = source.convert('RGBA')
        rgb = Image.alpha_composite(Image.new('RGBA', rgba.size, 'white'), rgba).convert('RGB')
        if first is None:
            first = rgb.copy()
        rgb.thumbnail((256, 256))
        frames.append(np.array(rgb.resize((64, 64), Image.Resampling.BILINEAR)))
        durations.append(max(10, int(source.info.get('duration', 100) or 100)))
        index += 1
    buffer = io.BytesIO()
    first.save(buffer, 'PNG')
    result = still_features(buffer.getvalue(), thumb_path)
    cumulative = np.cumsum(durations)
    sample_times = np.linspace(0, int(cumulative[-1])-1, 12)
    indices = np.searchsorted(cumulative, sample_times, side='right')
    result.update(sha256=hashlib.sha256(raw).hexdigest(), animated=True,
                  frames=index, duration_ms=int(cumulative[-1]),
                  animation_samples=[encode_array(frames[i]) for i in indices],
                  animation_version=1,media_version=2)
    # Retain larger visual samples for cross-format content embeddings.
    # Re-decode only selected positions; Pillow maintains GIF compositing.
    samples=[]
    for i in np.unique(indices)[::max(1,len(np.unique(indices))//8)][:8]:
        source.seek(int(i));rgba=source.convert('RGBA')
        rgb=Image.alpha_composite(Image.new('RGBA',rgba.size,'white'),rgba).convert('RGB')
        samples.append(np.array(ImageOps.pad(rgb,(256,256),color='white')))
    frame_path=thumb_path.with_suffix('.frames.npz')
    np.savez_compressed(frame_path,frames=np.stack(samples))
    result['frame_path']=str(frame_path)
    return result


def still_features(raw, thumb_path):
    with Image.open(io.BytesIO(raw)) as source:
        width, height = source.size
        if source.getexif().get(274) in (5, 6, 7, 8):
            width, height = height, width
        # JPEG decoder downsamples before allocating full-resolution pixels.
        # Resize before alpha compositing: three full-size RGBA copies used to
        # dominate both memory and decoding work on camera photographs.
        source.draft('RGB', (640, 640))
        source = ImageOps.exif_transpose(source)
        source.thumbnail((640, 640))
        if source.mode in ('RGBA', 'LA', 'P') or 'transparency' in source.info:
            rgba = source.convert('RGBA')
            rgb_image = Image.alpha_composite(Image.new('RGBA', rgba.size, 'white'), rgba).convert('RGB')
        else:
            rgb_image = source.convert('RGB')
        rgb = np.array(rgb_image)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        h, w = gray.shape
        hashes = [phash(np.rot90(rgb, k)) for k in range(4)]
        # A second hash helps discover small centered crops.
        if min(w, h) >= 40:
            crop = rgb[int(h*.04):int(h*.96), int(w*.04):int(w*.96)]
            hashes.extend(phash(np.rot90(crop, k)) for k in range(4))
        rgb_image.save(thumb_path, 'JPEG', quality=88)
        # Square normalization handles anisotropic resizing before feature extraction.
        normalized = cv2.resize(gray, (384, 384), interpolation=cv2.INTER_AREA)
        keypoints, descriptors = cv2.SIFT_create(nfeatures=350, contrastThreshold=.025).detectAndCompute(normalized, None)
        points = np.array([k.pt for k in keypoints], dtype=np.float32).reshape(-1, 2)
        descriptors = descriptors if descriptors is not None else np.empty((0, 128), np.float32)
        feature_path = str(thumb_path.with_suffix('.npz'))
        np.savez_compressed(feature_path, points=points, descriptors=descriptors.astype(np.uint8))
        small = cv2.resize(rgb, (32, 32), interpolation=cv2.INTER_AREA)
        return dict(sha256=hashlib.sha256(raw).hexdigest(), hashes=hashes,
                    width=width, height=height, sharpness=float(cv2.Laplacian(gray, cv2.CV_64F).var()),
                    color=encode_array(small), aspect=width / height,
                    feature_path=feature_path, signatures=descriptor_signatures(descriptors))


class BKTree:
    def __init__(self):
        self.root = None

    def add(self, value, index):
        if self.root is None:
            self.root = [value, [index], {}]
            return
        node = self.root
        while True:
            distance = (node[0] ^ value).bit_count()
            if distance == 0:
                node[1].append(index)
                return
            if distance not in node[2]:
                node[2][distance] = [value, [index], {}]
                return
            node = node[2][distance]

    def search(self, value, radius):
        pending = [self.root] if self.root else []
        while pending:
            current = pending.pop()
            distance = (current[0] ^ value).bit_count()
            if distance <= radius:
                yield from current[1]
            pending.extend(child for d, child in current[2].items() if distance-radius <= d <= distance+radius)


def image_statistics(rgb):
    rgb = rgb.astype(np.float32)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    mean = cv2.GaussianBlur(gray, (7, 7), 1.5)
    variance = cv2.GaussianBlur(gray * gray, (7, 7), 1.5) - mean * mean
    return gray, mean, variance, cv2.GaussianBlur(rgb, (3, 3), 0)


def structure(aa, bb, mask=None, max_color=None, target_stats=None):
    aa, bb = aa.astype(np.float32), bb.astype(np.float32)
    target_color = target_stats[3] if target_stats is not None else cv2.GaussianBlur(bb, (3, 3), 0)
    color_map = np.mean(np.abs(cv2.GaussianBlur(aa, (3, 3), 0) - target_color), axis=2) / 255
    color = float(np.mean(color_map if mask is None else color_map[mask]))
    if max_color is not None and color > max_color:
        return -1.0, color
    ga = cv2.cvtColor(aa, cv2.COLOR_RGB2GRAY)
    ma = cv2.GaussianBlur(ga, (7, 7), 1.5)
    va = cv2.GaussianBlur(ga * ga, (7, 7), 1.5) - ma * ma
    if target_stats is None:
        gb = cv2.cvtColor(bb, cv2.COLOR_RGB2GRAY)
        mb = cv2.GaussianBlur(gb, (7, 7), 1.5)
        vb = cv2.GaussianBlur(gb * gb, (7, 7), 1.5) - mb * mb
    else:
        gb, mb, vb = target_stats[:3]
    cov = cv2.GaussianBlur(ga * gb, (7, 7), 1.5) - ma * mb
    scores = ((2 * ma * mb + 6.5025) * (2 * cov + 58.5225)) / ((ma*ma + mb*mb + 6.5025) * (va+vb + 58.5225))
    return float(np.mean(scores if mask is None else scores[mask])), color


@lru_cache(maxsize=768)
def local_features(path):
    with np.load(path) as data:
        return data['points'], data['descriptors'].astype(np.float32)


@lru_cache(maxsize=96)
def comparison_image(path):
    from pathlib import Path
    # imdecode also supports Windows paths containing non-ASCII characters.
    raw = np.fromfile(Path(path).with_suffix('.jpg'), dtype=np.uint8)
    rgb = cv2.cvtColor(cv2.resize(cv2.imdecode(raw, cv2.IMREAD_COLOR), (384, 384)), cv2.COLOR_BGR2RGB)
    return rgb


@lru_cache(maxsize=16)
def comparison_statistics(path):
    return image_statistics(comparison_image(path))


def descriptor_matches(ad, bd):
    """Exact squared-L2 top two, evaluated by native matrix multiplication.

    Stored SIFT descriptors are uint8 values represented as float32. Their
    dot products/squared norms fit float32's exact integer range; this retains
    the BF matcher ratio test without approximate nearest-neighbor shortcuts.
    """
    distances = -2 * (ad @ bd.T)
    distances += np.einsum('ij,ij->i', ad, ad)[:, None]
    distances += np.einsum('ij,ij->i', bd, bd)[None, :]
    nearest = distances.argmin(axis=1)
    rows = np.arange(len(ad))
    first = distances[rows, nearest].copy()
    distances[rows, nearest] = np.inf
    second = distances.min(axis=1)
    accepted = np.flatnonzero(first < (.72**2)*second)
    return [cv2.DMatch(int(i), int(nearest[i]), float(first[i])) for i in accepted]


def geometric_compare(a, b, mode):
    if not a.get('feature_path') or not b.get('feature_path'):
        return None
    ap, ad = local_features(a['feature_path'])
    bp, bd = local_features(b['feature_path'])
    if min(len(ad), len(bd)) < 12:
        return None
    good = descriptor_matches(ad, bd)
    # One destination keypoint can only supply one correspondence.
    good = list({m.trainIdx: m for m in sorted(good, key=lambda x: -x.distance)}.values())
    if len(good) < 12:
        return None
    source = np.float32([ap[m.queryIdx] for m in good])
    target = np.float32([bp[m.trainIdx] for m in good])
    transform, inliers = cv2.estimateAffine2D(source, target, method=cv2.RANSAC, ransacReprojThreshold=3, maxIters=1500, confidence=.995)
    if transform is None or inliers.sum() < 12 or inliers.mean() < .55:
        return None
    mask = inliers.ravel().astype(bool)
    area_scale = float(np.linalg.det(transform[:, :2]))
    if area_scale <= 0:
        return None
    # Measure coverage relative to transformed image content, excluding the
    # empty canvas corners introduced by an expanded rotation.
    source_coverage = cv2.contourArea(cv2.convexHull(source[mask])) / (384**2 * min(1, 1/area_scale))
    target_coverage = cv2.contourArea(cv2.convexHull(target[mask])) / (384**2 * min(1, area_scale))
    if min(source_coverage, target_coverage) < .20:
        return None
    aa, bb = [comparison_image(p['feature_path']) for p in (a, b)]
    aligned = cv2.warpAffine(aa, transform, (384, 384))
    valid = cv2.warpAffine(np.ones((384, 384), np.uint8), transform, (384, 384), flags=cv2.INTER_NEAREST)
    valid = cv2.erode(valid, np.ones((11, 11), np.uint8)).astype(bool)
    # Expanded rotations introduce blank corners even for identical pictures.
    if valid.mean() < .40:
        return None
    score, color = structure(aligned, bb, valid, max_color=.085,
                             target_stats=comparison_statistics(b['feature_path']))
    if score < (.86 if mode != 'relaxed' else .78) or color > .085:
        return None
    return round(min(score, .999), 4), '旋转/缩放/拉伸：局部特征与几何对齐验证'


def compare_animation(a, b, mode):
    if not a.get('animated') or not b.get('animated'):
        return None
    if not a.get('animation_samples') or not b.get('animation_samples'):
        return None  # Partial recoveries are handled by content grouping.
    if abs(a['duration_ms']-b['duration_ms']) / max(a['duration_ms'], b['duration_ms']) > (.35 if mode == 'relaxed' else .2):
        return None
    aa, bb = [[np.frombuffer(base64.b64decode(s), np.uint8).reshape(64,64,3) for s in p['animation_samples']] for p in (a,b)]
    for k in range(4):
        scores = []
        for x, y in zip(aa, bb):
            y = np.rot90(y,k).copy()
            # White backgrounds can hide a changed animated foreground in an
            # average score. Also reject a substantial strongly changed area.
            delta = np.mean(np.abs(x.astype(np.float32)-y.astype(np.float32)), axis=2)/255
            if np.mean(delta > .18) > (.06 if mode=='relaxed' else .03):
                break
            score, color = structure(x, y, max_color=.10)
            if color > .10 or score < (.75 if mode == 'relaxed' else .84):
                break
            scores.append(score)
        if len(scores) == 12:
            return round(min(min(scores), .999),4), '动画时间轴 12 帧抽样相似（并非逐帧完全相同）'
    return None


def compare(a, b, mode='strict'):
    if mode == 'variants':
        from .variants import compare as compare_variants
        return compare_variants(a, b)
    if a['sha256'] == b['sha256']:
        return 1.0, '文件完全相同'
    if a.get('media_type')=='video' or b.get('media_type')=='video':
        return None  # Different videos need content mode, never cover-only dedup.
    if a.get('animated') or b.get('animated'):
        return compare_animation(a, b, mode)
    distance = min((x ^ y).bit_count() for x in a['hashes'] for y in b['hashes'])
    if distance <= (8 if mode != 'relaxed' else 12):
        aa, bb = [np.frombuffer(base64.b64decode(p['color']), dtype=np.uint8).reshape(32, 32, 3) for p in (a, b)]
        for k in range(4):
            ssim, color_error = structure(aa, np.rot90(bb, k).copy(), max_color=.065 if mode != 'relaxed' else .10)
            if color_error <= (0.065 if mode != 'relaxed' else .10) and ssim >= (.88 if mode != 'relaxed' else .76):
                return round(max(0, min(ssim, .999)), 4), '视觉相似，需人工确认'
    if mode in ('strong', 'relaxed'):
        return geometric_compare(a, b, mode)
    return None


class LocalIndex:
    """Multi-table descriptor LSH. Limit common buckets to control repeated patterns."""
    def __init__(self):
        self.tables = [{} for _ in range(4)]

    def buckets(self, signatures):
        return {(i, (sig >> (i*16)) & 65535) for sig in signatures for i in range(4)}

    def add(self, photo, index):
        for i, key in self.buckets(photo.get('signatures', [])):
            bucket = self.tables[i].setdefault(key, set())
            if bucket is not None:
                bucket.add(index)
                if len(bucket) > 100:
                    self.tables[i][key] = None

    def search(self, photo):
        from collections import Counter
        votes = Counter()
        for i, key in self.buckets(photo.get('signatures', [])):
            bucket = self.tables[i].get(key)
            if bucket:
                votes.update(bucket)
        return [index for index, count in votes.most_common(16) if count >= 4]


def quality(p):
    # Resolution first; sharpness is only a reference, never a deletion decision.
    return p['width'] * p['height'], p['sharpness'], p['size']


def cluster(photos, mode='strict', scope='all', progress=None, cancelled=lambda: False, pair_cache=None,rules=None):
    from .acceleration import cpu_budget
    with cpu_budget():
        return _cluster(photos,mode,scope,progress,cancelled,pair_cache,rules)


def _cluster(photos, mode, scope, progress, cancelled, pair_cache=None,rules=None):
    from .index import HammingIndex, PostingIndex
    from .acceleration import workers
    order = sorted(photos, key=quality, reverse=True)
    tree = HammingIndex(len(order))
    local_index = PostingIndex(order) if mode in ('strong', 'relaxed', 'variants') else None
    with ThreadPoolExecutor(max_workers=workers(), thread_name_prefix='match') as executor:
        return _cluster_order(order, mode, scope, progress, cancelled, tree, local_index, executor,pair_cache,rules)


def _cluster_order(order, mode, scope, progress, cancelled, tree, local_index, executor,pair_cache=None,rules=None):
    groups, representatives = [], []
    exact = {}
    for i, photo in enumerate(order):
        if cancelled():
            return None
        identity = (photo.get('sha256'), photo['album'] if scope == 'album' else '')
        exact_group = exact.get(identity) if photo.get('sha256') else None
        if exact_group is not None:
            groups[exact_group].append(dict(photo, score=1.0, reason='文件完全相同'))
            if progress:
                progress(i+1, len(order))
            continue
        candidates = set(tree.search(photo['hashes'], 8 if mode != 'relaxed' else 12))
        if local_index is not None:
            candidates.update(local_index.search(i, limit=32 if mode=='variants' else 16))
        best = None
        candidates = [j for j in sorted(candidates) if scope != 'album' or representatives[j]['album'] == photo['album']]
        if candidates and mode == 'variants':
            from .variants import load
            load(photo['variant_path'])  # Avoid concurrent decompression of the query.
        if candidates and mode in ('strong', 'relaxed') and photo.get('feature_path'):
            # All candidate tasks share this query. Populate once before fanout
            # rather than racing to open/decompress it in every worker.
            local_features(photo['feature_path'])
        def match_candidate(j):
            return compare(representatives[j], photo, mode)
        if candidates and mode=='variants':
            from .variants import compare_candidates
            matches=compare_candidates(representatives, photo, candidates, executor,pair_cache,rules)
        else:
            matches = executor.map(match_candidate, candidates) if len(candidates) >= 4 else map(match_candidate, candidates)
        for j, match in zip(candidates, matches):
            if match and (best is None or match[0] > best[1][0]):
                best = j, match
        if best is not None:
            j, (score, reason) = best
            groups[j].append(dict(photo, score=score, reason=reason))
        else:
            j = len(representatives)
            representatives.append(photo)
            groups.append([dict(photo, score=1, reason='建议保留参考：分辨率优先')])
            tree.add(photo['hashes'], j)
            if local_index is not None:
                local_index.add(i, j)
            if photo.get('sha256'):
                exact[identity] = j
        if progress:
            progress(i+1, len(order))
    # Every member matches the representative; no transitive A-B-C grouping.
    return sorted([g for g in groups if len(g) > 1], key=len, reverse=True)
