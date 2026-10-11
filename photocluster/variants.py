"""Local same-source matching, independent of semantic categories.

Bounded candidate retrieval -> SIFT correspondences -> homography -> majority
tile verification. Small residual deformation is allowed only after geometry
passes. Sampled video matches establish shared imagery, never file equality.
"""
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
import os

import cv2
import numpy as np
import psutil

from . import vision
from .rules import normalize_rules

VERSION = 1
YY,XX=np.mgrid[:384,:384].astype(np.float32)
PAD_INDEX=np.concatenate([np.arange(n,n+64)[np.pad(np.arange(64),(3,3),mode='reflect')] for n in range(0,384,64)])


def tile_canvas(image):
    return image[PAD_INDEX[:,None],PAD_INDEX[None,:]].astype(np.float32)


@lru_cache(maxsize=16)
def target_statistics(path,index):
    image=tile_canvas(frame_image(path,index))
    gray=cv2.cvtColor(image,cv2.COLOR_RGB2GRAY)
    mean=cv2.GaussianBlur(gray,(7,7),1.5)
    variance=cv2.GaussianBlur(gray*gray,(7,7),1.5)-mean*mean
    return cv2.GaussianBlur(image,(3,3),0),gray,mean,variance


def prepare(photo, force=False):
    from .frame_policy import sampling_identity
    sampled = sampling_identity(photo)
    path = Path(photo['feature_path']).with_suffix('.variants.npz')
    if path.exists() and not force:
        with np.load(path) as data:
            if (str(data['sha']) == photo['sha256'] and int(data['version']) == VERSION
                    and (str(data['sampling']) if 'sampling' in data else '') == sampled):
                return dict(photo, variant_path=str(path), hashes=data['hashes'].tolist(),
                            signatures=data['signatures'].tolist())
    images = [vision.comparison_image(photo['feature_path'])]
    if photo.get('frame_path') and Path(photo['frame_path']).exists():
        with np.load(photo['frame_path']) as data:
            frames = data['frames']
            images = [cv2.resize(frames[i], (384, 384)) for i in
                      np.unique(np.linspace(0, len(frames)-1, min(3, len(frames))).astype(int))]
    values, hashes, signatures = {}, [], []
    sift = cv2.SIFT_create(nfeatures=600, contrastThreshold=.018)
    for i, image in enumerate(images):
        values[f'image{i}'] = image
        for flip in range(2):
            rgb = np.ascontiguousarray(image[:, ::-1] if flip else image)
            kp, desc = sift.detectAndCompute(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), None)
            desc = desc if desc is not None else np.empty((0, 128), np.float32)
            values[f'p{i}_{flip}'] = np.float32([p.pt for p in kp]).reshape(-1, 2)
            values[f'd{i}_{flip}'] = desc.astype(np.uint8)
            signatures.extend(vision.descriptor_signatures(desc))
            hashes.extend(vision.phash(np.rot90(rgb, k)) for k in range(4))
    hashes = np.unique(np.asarray(hashes, np.uint64))
    signatures = np.unique(np.asarray(signatures, np.uint64))
    np.savez_compressed(path, **values, count=len(images), hashes=hashes,
                        signatures=signatures, sha=photo['sha256'], version=VERSION, sampling=sampled)
    # A sampling upgrade may rewrite the same path with different frame data.
    load.cache_clear();frame_image.cache_clear();target_statistics.cache_clear()
    return dict(photo, variant_path=str(path), hashes=hashes.tolist(), signatures=signatures.tolist())


@lru_cache(maxsize=min(4096,max(64,int(psutil.virtual_memory().available*.10/(2*1024**2)))))
def load(path):
    with np.load(path) as data:
        result={k: data[k].astype(np.float32) if k.startswith('d') else data[k]
                for k in data.files if k=='count' or k.startswith(('d','p'))}
        result['_path']=path
        return result


@lru_cache(maxsize=128)
def frame_image(path,index):
    with np.load(path) as data:return data[f'image{index}']


def get_image(data,index):
    return data[f'image{index}'] if f'image{index}' in data else frame_image(data['_path'],index)


def tile_score(a, b, valid, target_stats=None):
    # Pack reflected tile borders into one canvas: identical tile-local blur,
    # with a handful of OpenCV calls instead of hundreds of tiny calls.
    def tiles(x):return x.reshape(6,64,6,64,*x.shape[2:]).swapaxes(1,2)
    def core(x):return x.reshape(6,70,6,70,*x.shape[2:]).swapaxes(1,2)[:,:,3:-3,3:-3]
    mask=tiles(valid);counts=mask.sum(axis=(2,3));eligible=counts>=64*64*.75
    if eligible.sum()<12:
        return None
    aa=tile_canvas(a)
    if target_stats is None:
        bb=tile_canvas(b);gb=cv2.cvtColor(bb,cv2.COLOR_RGB2GRAY)
        mb=cv2.GaussianBlur(gb,(7,7),1.5)
        vb=cv2.GaussianBlur(gb*gb,(7,7),1.5)-mb*mb
        blur_b=cv2.GaussianBlur(bb,(3,3),0)
    else:blur_b,gb,mb,vb=target_stats
    color=cv2.transform(cv2.absdiff(cv2.GaussianBlur(aa,(3,3),0),blur_b),np.full((1,3),1/765,np.float32))
    ga=cv2.cvtColor(aa,cv2.COLOR_RGB2GRAY)
    ma=cv2.GaussianBlur(ga,(7,7),1.5)
    va=cv2.GaussianBlur(ga*ga,(7,7),1.5)-ma*ma
    cov=cv2.GaussianBlur(ga*gb,(7,7),1.5)-ma*mb
    smap=((2*ma*mb+6.5025)*(2*cov+58.5225))/((ma*ma+mb*mb+6.5025)*(va+vb+58.5225))
    colors=(core(color)*mask).sum(axis=(2,3))/np.maximum(counts,1)
    scores=(core(smap)*mask).sum(axis=(2,3))/np.maximum(counts,1)
    scores=np.where(colors<=.14,scores,0)[eligible]
    # Added captions/objects may change a minority, not most of the image.
    scores = np.asarray(scores)
    if (scores >= .70).mean() < .65 or np.median(scores) < .78:
        return None
    return float(np.mean(np.sort(scores)[int(len(scores)*.25):]))


def frame_match(a, b, i, j, flip, matches=None,rules=None):
    rules=normalize_rules(rules)
    ap, ad = a[f'p{i}_{flip}'], a[f'd{i}_{flip}']
    bp, bd = b[f'p{j}_0'], b[f'd{j}_0']
    if min(len(ad), len(bd)) < 14:
        return None
    if matches is None:
        matches = vision.descriptor_matches(ad, bd)
    good = list({m.trainIdx: m for m in sorted(matches, key=lambda m: -m.distance)}.values())
    if len(good) < 14:
        return None
    src = np.float32([ap[m.queryIdx] for m in good])
    dst = np.float32([bp[m.trainIdx] for m in good])
    # An inlier subset cannot cover more area than all correspondences.
    # Reject impossible geometry before running up to 1800 RANSAC iterations.
    if min(cv2.contourArea(cv2.convexHull(points))/384**2 for points in (src,dst)) < .22:
        return None
    if rules['perspective']:
        matrix, inliers = cv2.findHomography(src, dst, cv2.USAC_MAGSAC, 5, maxIters=1800, confidence=.995)
    else:
        affine,inliers=cv2.estimateAffine2D(src,dst,method=cv2.RANSAC,ransacReprojThreshold=5,maxIters=1800,confidence=.995)
        matrix=np.vstack((affine,[0,0,1])) if affine is not None else None
    if matrix is None or not np.isfinite(matrix).all() or inliers.sum() < 14 or inliers.mean() < .45:
        return None
    keep = inliers.ravel().astype(bool)
    if min(cv2.contourArea(cv2.convexHull(points[keep])) / 384**2 for points in (src, dst)) < .22:
        return None
    corners = np.float32([[0,0], [383,0], [383,383], [0,383]]).reshape(-1,1,2)
    projected = cv2.perspectiveTransform(corners, matrix)
    if not cv2.isContourConvex(projected) or not .25 < abs(cv2.contourArea(projected))/384**2 < 4:
        return None
    image=get_image(a,i)
    aa = np.ascontiguousarray(image[:, ::-1] if flip else image)
    bb = get_image(b,j)
    aligned = cv2.warpPerspective(aa, matrix, (384, 384))
    valid = cv2.warpPerspective(np.ones((384,384), np.uint8), matrix, (384,384), flags=cv2.INTER_NEAREST)
    valid = cv2.erode(valid, np.ones((13,13), np.uint8)).astype(bool)
    if valid.mean() < .5:
        return None
    stats=target_statistics(b['_path'],j) if '_path' in b else None
    score = tile_score(aligned, bb, valid,stats)
    if score is not None:
        return score
    if not rules['warp']:
        return None
    # Infer a smooth residual field from verified correspondences. Dense
    # optical flow searched every pixel of thousands of ultimately rejected
    # pairs; sparse evidence already supplies the actual displacement.
    projected_points=cv2.perspectiveTransform(src[keep,None,:],matrix)[:,0,:]
    locations=dst[keep]
    residual=projected_points-locations
    grid=np.zeros((48,48,3),np.float32)
    xy=np.clip(np.rint(locations/8).astype(int),0,47)
    for point,delta in zip(xy,residual):
        grid[point[1],point[0],:2]+=delta
        grid[point[1],point[0],2]+=1
    smooth=cv2.GaussianBlur(grid,(0,0),3)
    field=smooth[:,:,:2]/np.maximum(smooth[:,:,2,None],1e-6)
    flow=cv2.resize(field,(384,384),interpolation=cv2.INTER_LINEAR)
    magnitude = cv2.magnitude(flow[:,:,0],flow[:,:,1])
    if np.quantile(magnitude[valid], .95) > 12:
        return None
    flow = cv2.GaussianBlur(flow, (0,0), 3)
    mx, my = XX+flow[:,:,0], YY+flow[:,:,1]
    refined = cv2.remap(aligned, mx, my, cv2.INTER_LINEAR)
    mask = valid & (cv2.remap(valid.astype(np.uint8), mx, my, cv2.INTER_NEAREST) > 0)
    if mask.mean() < .5:
        return None
    return tile_score(refined, bb, mask,stats)


def compare(a, b, prepared_matches=None,rules=None):
    rules=normalize_rules(rules)
    if a['sha256'] == b['sha256']:
        return 1., '文件完全相同'
    aa, bb = load(a['variant_path']), load(b['variant_path'])
    temporal = lambda p: p.get('animated') or p.get('media_type') == 'video'
    needed = 2 if temporal(a) and temporal(b) else 1
    used_a, used_b, scores = set(), set(), []
    for i in range(int(aa['count'])):
        for j in range(int(bb['count'])):
            if i in used_a or j in used_b:
                continue
            for flip in range(2 if rules['mirror'] else 1):
                matches = prepared_matches.get((i,j,flip)) if prepared_matches is not None else None
                score = frame_match(aa, bb, i, j, flip, matches,rules)
                if score is not None:
                    scores.append(score); used_a.add(i); used_b.add(j)
                    break
            if len(scores) >= needed:
                reason = '同源关键帧：存在共同画面，不代表整段动画/视频重复' if temporal(a) or temporal(b) else '同源画面变体：局部特征、几何对齐及多数区域验证'
                return round(min(min(scores), .999), 4), reason
    return None


def compare_candidates(representatives, photo, candidates, executor, cache=None,rules=None):
    if cache is None:
        return _compare_candidates(representatives,photo,candidates,executor,rules)
    ids,b,found=cache.query([representatives[j] for j in candidates],photo)
    missing=[(n,j) for n,j in enumerate(candidates) if ids[n] not in found]
    values=list(_compare_candidates(representatives,photo,[j for n,j in missing],executor,rules)) if missing else []
    cache.save([ids[n] for n,j in missing],b,values)
    completed={ids[n]:value for (n,j),value in zip(missing,values)}
    return [found[a] if a in found else completed[a] for a in ids]


def _compare_candidates(representatives, photo, candidates, executor,rules=None):
    rules=normalize_rules(rules)
    if os.environ.get('PHOTOCLUSTER_GEOMETRY_GPU','1')=='1':
        from .geometry_gpu import match_sources
        from .acceleration import cuda
        if cuda() is not None:
            target=load(photo['variant_path'])
            sources=list(executor.map(lambda j:load(representatives[j]['variant_path']),candidates))
            maps=match_sources(sources,target,mirror=rules['mirror'])
            if maps is not None:
                return executor.map(lambda item:compare(representatives[item[1]],photo,maps[item[0]],rules),enumerate(candidates))
    from .acceleration import cuda, descriptor_batch
    # Small SIFT tasks were slower end-to-end on CUDA on the reference laptop.
    # Keep the benchmark path opt-in; dense semantic retrieval uses GPU by default.
    if os.environ.get('PHOTOCLUSTER_SIFT_GPU')!='1' or cuda() is None:
        return executor.map(lambda j:compare(representatives[j],photo,rules=rules),candidates)
    target=load(photo['variant_path'])
    sources=list(executor.map(lambda j:load(representatives[j]['variant_path']),candidates))
    maps=[{} for _ in candidates];pairs=[];owners=[]
    for n,source in enumerate(sources):
        for i in range(int(source['count'])):
            for j in range(int(target['count'])):
                for flip in range(2 if rules['mirror'] else 1):
                    a,b=source[f'd{i}_{flip}'],target[f'd{j}_0']
                    if min(len(a),len(b))>=14:
                        pairs.append((a,b));owners.append((n,(i,j,flip)))
    matches=descriptor_batch(pairs) if pairs else []
    if matches is None:
        return executor.map(lambda j:compare(representatives[j],photo,rules=rules),candidates)
    for (n,key),value in zip(owners,matches):maps[n][key]=value
    return executor.map(lambda item:compare(representatives[item[1]],photo,maps[item[0]],rules),enumerate(candidates))


def cluster(photos, scope, progress, cancelled, force=False, pair_cache=None,rules=None):
    from .acceleration import cpu_budget
    with cpu_budget():
        return _cluster(photos,scope,progress,cancelled,force,pair_cache,normalize_rules(rules))


def _cluster(photos, scope, progress, cancelled, force=False, pair_cache=None,rules=None):
    from .acceleration import workers
    load.cache_clear()
    frame_image.cache_clear()
    target_statistics.cache_clear()
    prepared = []
    # Bounded batches prevent loading the entire library into the task queue.
    with ThreadPoolExecutor(max_workers=workers()) as pool:
        for start in range(0, len(photos), 24):
            if cancelled():
                return None
            for photo in pool.map(lambda p: prepare(p, force), photos[start:start+24]):
                prepared.append(photo)
                progress(len(prepared), len(photos), 'variant_features')
    return vision.cluster(prepared, 'variants', scope,
                          lambda done,total: progress(done,total,'variant_match'), cancelled, pair_cache,rules)
