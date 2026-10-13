import concurrent.futures
import hashlib
import json
import os
import sqlite3
import threading
import time
import tempfile
from pathlib import Path

from . import adb, vision
from .rules import normalize_rules,pair_version

from .config import ROOT, DATA
THUMBS = DATA / 'thumbnails'


class Service:
    def __init__(self, data=DATA):
        self.data = Path(data)
        self.thumbs = self.data / 'thumbnails'
        self.thumbs.mkdir(parents=True, exist_ok=True)
        self.db = self.data / 'catalog.sqlite3'
        with self.connect() as con:
            con.execute('PRAGMA journal_mode=WAL')
            con.execute('CREATE TABLE IF NOT EXISTS features (key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            con.execute('CREATE TABLE IF NOT EXISTS skipped (key TEXT PRIMARY KEY, error TEXT NOT NULL)')
            # GIF support replaces the old permanent "animation unsupported" skip.
            con.execute('DELETE FROM skipped WHERE error=?', ('动态图片暂不比较，避免只比较第一帧',))
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.scan_thread = None
        self.status = dict(running=False, phase='idle', message='连接手机后刷新相册', done=0, total=0, errors=0)
        self.catalog = self.read_json('catalog.json', {'serial': None, 'photos': []})
        self.result = self.read_json('groups.json', {'groups': [], 'summary': None})
        self.sync_status = dict(running=False,phase='idle',message='等待同步',count=0)

    def connect(self):
        return sqlite3.connect(self.db, timeout=30)

    def read_json(self, name, default):
        path = self.data / name
        return json.loads(path.read_text('utf-8')) if path.exists() else default

    def save(self, name, value):
        target = self.data / name
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False), 'utf-8')
        temporary.replace(target)

    def update(self, **values):
        with self.lock:
            self.status.update(values)

    def normalize_groups(self):
        """After edits, a sole remaining member belongs in the unmatched folder."""
        remaining, unmatched = [], {p['key']:p for p in self.result.get('ungrouped', [])}
        for group in self.result['groups']:
            if len(group['photos']) > 1:
                remaining.append(group)
            elif group['photos']:
                p = group['photos'][0]
                unmatched[p['key']] = dict(p, score=0, reason='原分组仅剩此文件；可重新分类查找其他匹配')
        self.result['groups'] = remaining
        self.result['ungrouped'] = list(unmatched.values())
        self.result['summary']['ungrouped'] = len(unmatched)

    @staticmethod
    def key(serial, p):
        return hashlib.sha256(json.dumps([3, serial, p['path'], p['size'], p['modified']], ensure_ascii=False).encode()).hexdigest()

    def refresh(self, serial, internal=False):
        # Do not hold the state lock across ADB I/O: polling must remain responsive.
        with self.lock:
            if (self.status['running'] and not internal) or self.sync_status['running']:
                raise ValueError('扫描期间不能刷新相册')
            self.sync_status=dict(running=True,phase='reading',message='正在读取手机图片与视频目录…',count=0,started_at=time.time())
        try:
            photos = adb.inventory(serial)
        except Exception as exc:
            with self.lock:self.sync_status.update(running=False,phase='error',message=str(exc))
            raise
        with self.lock:
            self.sync_status.update(phase='indexing',message='正在更新相册与失效记录…',count=len(photos))
            for p in photos:
                p['key'] = self.key(serial, p)
            previous = {p['key'] for p in self.catalog['photos']} if serial == self.catalog['serial'] else set()
            current = {p['key'] for p in photos}
            changes = dict(added=len(current-previous), removed=len(previous-current))
            self.catalog = dict(serial=serial, photos=photos, refreshed_at=time.time(), changes=changes)
            self.save('catalog.json', self.catalog)
            # Invalidate stale group entries after external phone edits. Device
            # switches must never leave actionable results from another phone.
            if self.result.get('summary'):
                if self.result['summary']['serial'] != serial:
                    self.result = {'groups': [], 'summary': None}
                else:
                    valid = {p['key'] for p in photos}
                    by_key = {p['key']: p for p in photos}
                    self.result['ungrouped'] = [dict(p, taken=by_key[p['key']].get('taken', 0))
                                                for p in self.result.get('ungrouped', []) if p['key'] in valid]
                    self.result['summary']['ungrouped'] = len(self.result['ungrouped'])
                    for group in self.result['groups']:
                        group['photos'] = [p for p in group['photos'] if p['key'] in valid]
                        for p in group['photos']:
                            p['modified'] = by_key[p['key']]['modified']
                            p['taken'] = by_key[p['key']].get('taken', 0)
                        group['potential_bytes'] = 0 if group.get('kind') in ('content','variants','subject') else sum(p['size'] for p in group['photos'][1:])
                    self.normalize_groups()
                    self.result['summary'].update(groups=len(self.result['groups']),
                        grouped_photos=sum(len(g['photos']) for g in self.result['groups']),
                        potential_bytes=sum(g['potential_bytes'] for g in self.result['groups']))
                    if changes['added'] or changes['removed']:
                        self.result['summary']['stale'] = True
                self.save('groups.json', self.result)
            self.sync_status.update(running=False,phase='done',message=f'同步完成：{len(photos)} 个媒体文件',finished_at=time.time(),changes=changes)
            return self.albums()

    def albums(self):
        albums = {}
        with self.connect() as con:
            cached = {r[0] for r in con.execute('SELECT key FROM features')}
        for p in self.catalog['photos']:
            album = albums.setdefault(p['album'], dict(path=p['album'], name=p['album_name'], count=0, size=0, cached=0))
            album['count'] += 1
            album['size'] += p['size']
            album['cached'] += p['key'] in cached
        return dict(serial=self.catalog['serial'], refreshed_at=self.catalog.get('refreshed_at'),
                    changes=self.catalog.get('changes', {}),
                    count=len(self.catalog['photos']), albums=sorted(albums.values(), key=lambda a: -a['count']))

    def start(self, albums, mode, scope, limit, force=False, all_albums=False, serial=None, threshold=.84, rules=None, subject_engine='general'):
        rules=normalize_rules(rules) if mode=='variants' else None
        with self.lock:
            if self.status['running'] or self.sync_status['running']:
                raise ValueError('已有扫描正在运行')
            if mode=='subject':
                from . import subject
                encoder=subject.backend(subject_engine)
                ready=encoder.installed() if subject_engine=='auto' else encoder.MODEL.exists()
                if not ready:raise ValueError('请先准备主体识别资源')
            serial = serial or self.catalog['serial']
            if not serial:
                raise ValueError('请先刷新手机相册')
            if not albums and not all_albums:
                raise ValueError('请至少选择一个非空相册')
            self.cancel.clear()
            self.status = dict(running=True, phase='refresh', message='同步手机最新媒体目录', done=0,
                               total=0, errors=0, cached=0, started_at=time.time(), current='', force=force,mode=mode,rules=rules)
            self.scan_thread = threading.Thread(target=self.scan_request, args=(serial, albums, mode, scope, limit, force, all_albums, threshold,rules,subject_engine), daemon=True)
            self.scan_thread.start()
            return dict(self.status)

    def scan_request(self, serial, albums, mode, scope, limit, force, all_albums, threshold=.84,rules=None,subject_engine='general'):
        try:
            self.refresh(serial, internal=True)
            photos = [dict(p) for p in self.catalog['photos'] if all_albums or p['album'] in albums]
            if limit:
                photos = photos[:limit]
            self.update(phase='scan', total=len(photos), message='重新读取全部所选原图' if force else '增量扫描：复用未变化的图片特征')
            self.worker(serial, photos, mode, scope, force=force,threshold=threshold,rules=rules,subject_engine=subject_engine)
        except Exception as exc:
            self.update(running=False, phase='error', message=str(exc))

    def worker(self, serial, photos, mode, scope, force=False,threshold=.84,rules=None,subject_engine='general'):
        rules=normalize_rules(rules) if mode=='variants' else None
        errors, processed = [], []
        started = time.perf_counter()
        try:
            if force:
                vision.local_features.cache_clear()
                vision.comparison_image.cache_clear()
                vision.comparison_statistics.cache_clear()
                self.scan_photos(serial, photos, processed, errors, started, force=True)
            else:
                self.scan_photos(serial, photos, processed, errors, started)
            scan_seconds = time.perf_counter() - started
            review_items=errors+[dict(p,error=p['warning'],analyzed=True) for p in processed if p.get('warning')]
            self.save('errors.json', [{k:v for k,v in p.items() if k not in ('hashes','color','signatures','animation_samples','feature_path','frame_path')} for p in review_items])
            self.update(review_count=len(review_items))
            if self.cancel.is_set():
                self.update(phase='stopped', message='已停止，图片特征已保存；再次扫描会复用缓存')
                return
            # Failed files are visible independently of group results. Preserve
            # partial recovery warnings in review cards even on cached scans.
            self.update(phase='cluster', message='匹配相似媒体', done=0, total=len(processed))
            # Match reuse applies only to an identical input set, mode, scope,
            # and algorithm version. It never suppresses fresh-file scanning.
            signature_fields=[11 if mode=='variants' else 7,mode,scope,threshold,sorted((p['key'],p['sha256']) for p in processed)]
            from .frame_policy import sampling_identity
            sampled = [(p['key'], version) for p in processed if (version := sampling_identity(p))]
            if sampled:signature_fields.append(sorted(sampled))
            if mode in ('content','subject'):
                from . import semantic, subject
                signature_fields.append((subject.backend(subject_engine) if mode=='subject' else semantic).model_identity())
            if rules is not None:signature_fields.append(rules)
            signature = hashlib.sha256(json.dumps(signature_fields).encode()).hexdigest()
            reusable = self.read_json('match-cache.json', {})
            cache_file = 'matches/'+signature+'.json'
            if reusable.get('signature') != signature:
                reusable = self.read_json(cache_file, {})
            cluster_started = time.perf_counter()
            if not force and reusable.get('signature') == signature:
                lookup = {p['key']: p for p in processed}
                groups = [[dict(lookup[x['key']], **{k:v for k,v in x.items() if k!='key'}) for x in group]
                          for group in reusable['groups']]
                self.update(message='已复用相同媒体集合的分类结果', reused_matches=True)
            else:
                def report(done, total):
                    seconds = time.perf_counter() - cluster_started
                    rate = done / seconds if seconds else 0
                    self.update(done=done, total=total, phase_seconds=round(seconds, 1),
                                rate=round(rate, 1), eta_seconds=round((total-done)/rate) if rate else None)
                if mode in ('content','subject'):
                    from . import semantic, subject
                    stage={'name':None,'started':time.perf_counter()}
                    def content_report(done,total,phase):
                        if stage['name']!=phase:stage.update(name=phase,started=time.perf_counter())
                        seconds=time.perf_counter()-stage['started'];rate=done/max(seconds,.001)
                        messages={'embedding':'本地模型分析关键帧内容','content_match':'跨格式内容归组',
                                  'subject_embedding':'本地主体模型提取整图与区域特征','subject_match':'自动发现主体分组（实验）',
                                  'character_embedding':'本地动漫角色模型提取身份特征','character_match':'按动漫角色身份归组（实验）',
                                  'subject_routing':'分析主体识别线索','subject_supplement':'补充主体特征','subject_verify':'核验候选主体的感知细节',
                                  'subject_consolidate':'复核主体组与共同参考图',
                                  'subject_complement':'提取主体补充复核特征','subject_complement_match':'查找遗漏的主体组关联',
                                  'subject_local_retrieval':'复用身份特征补查候选','subject_local_context':'按需核验主体局部细节',
                                  'subject_singletons':'复核未归组媒体的主体证据',
                                  'subject_extra_identity':'按需联合核验主体身份'}
                        self.update(phase=phase,message=messages[phase])
                        self.update(done=done,total=total,phase_seconds=round(seconds,1),rate=round(rate,1),eta_seconds=round((total-done)/rate) if rate else None)
                    groups=(subject.backend(subject_engine) if mode=='subject' else semantic).cluster(processed,self.thumbs,scope,threshold,content_report,self.cancel.is_set,force)
                elif mode == 'variants':
                    from . import variants
                    from .pair_cache import PairCache
                    if force and (self.data/'geometry-pairs.sqlite3').exists():
                        with sqlite3.connect(self.data/'geometry-pairs.sqlite3') as pairs:
                            pairs.execute('DELETE FROM pairs')
                    pair_cache = None if force else PairCache(self.data/'geometry-pairs.sqlite3',pair_version(rules))
                    stage = {'phase': None}
                    feature_stats = {}
                    def variant_report(done, total, phase):
                        if stage['phase'] != phase:
                            stage.update(phase=phase, started=time.perf_counter())
                        seconds = time.perf_counter()-stage['started']
                        rate = done/max(seconds,.001)
                        self.update(phase=phase, message=(f"同源特征：复用 {feature_stats.get('feature_cached',0)} 个，计算 {feature_stats.get('feature_computed',0)} 个" if phase=='variant_features' else '验证同源画面与几何变换'),
                                    done=done,total=total,rate=round(rate,1),eta_seconds=round((total-done)/rate) if rate else None,
                                    phase_seconds=round(seconds,1),**feature_stats,
                                    verified_pairs=pair_cache.computed if pair_cache else 0,reused_pairs=pair_cache.hits if pair_cache else 0)
                    try:
                        groups = variants.cluster(processed, scope, variant_report, self.cancel.is_set, force,pair_cache,rules,feature_stats)
                    finally:
                        if pair_cache:pair_cache.close()
                else:
                    groups = vision.cluster(processed, mode, scope, progress=report, cancelled=self.cancel.is_set)
            match_seconds = time.perf_counter() - cluster_started
            if groups is None:
                self.update(phase='stopped', message='已停止，图片特征已保存')
                return
            match_result = dict(signature=signature, groups=[
                [{k: p[k] for k in ('key', 'score', 'reason','relation','match_frame','reference_frame','subject_evidence') if k in p} for p in group] for group in groups])
            self.save('match-cache.json', match_result)
            (self.data/'matches').mkdir(exist_ok=True)
            self.save(cache_file, match_result)
            # Keep recent mode/scope combinations, not an unlimited history.
            caches=sorted((self.data/'matches').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
            for old in caches[16:]:old.unlink()
            public_groups = []
            private = ('hashes', 'color', 'aspect', 'signatures', 'feature_path', 'animation_samples','frame_path','variant_path')
            for n, group in enumerate(groups):
                public = [{k: v for k, v in p.items() if k not in private} for p in group]
                public_groups.append(dict(id=n+1, photos=public,kind=mode if mode in ('content','variants','subject') else 'duplicate',potential_bytes=0 if mode in ('content','variants','subject') else sum(p['size'] for p in group[1:])))
            grouped_keys = {p['key'] for g in groups for p in g}
            ungrouped = [dict({k:v for k,v in p.items() if k not in private},
                             reason='本次扫描范围及模式下未找到匹配', score=0)
                         for p in processed if p['key'] not in grouped_keys]
            summary = dict(serial=serial, scanned=len(processed), requested=len(photos), errors=len(errors),
                           groups=len(groups), grouped_photos=sum(len(g) for g in groups),
                           ungrouped=len(ungrouped),
                           potential_bytes=sum(g['potential_bytes'] for g in public_groups),
                           mode=mode, scope=scope, threshold=threshold,rules=rules,finished_at=time.time(), force=force, stale=False,
                           animated=sum(bool(p.get('animated')) for p in processed),
                           scan_seconds=round(scan_seconds, 2), match_seconds=round(match_seconds, 2),
                           total_seconds=round(time.perf_counter()-started, 2))
            result = dict(groups=public_groups, ungrouped=ungrouped, summary=summary)
            if mode=='subject':summary['subject_engine']=subject_engine
            if mode=='subject' and subject_engine=='auto':
                from .subject_auto import VERSION
                from . import perceptual, complementary, identity_refine, domain_refine, local_context, identity_extra
                summary['subject_policy']=VERSION
                summary['subject_perceptual']=perceptual.installed()
                summary['subject_complementary']=complementary.installed()
                summary['subject_identity_refine']=complementary.installed() and identity_refine.installed()
                summary['subject_domain_refine']=summary['subject_identity_refine'] and domain_refine.installed()
                summary['subject_local_context']=local_context.installed()
                summary['subject_identity_extra']=identity_extra.installed()
            self.save('groups.json', result)
            with self.lock:
                self.result = result
            self.update(phase='done', message='扫描完成，请逐组检查相似媒体', done=len(processed), total=len(processed),
                        scan_seconds=round(scan_seconds, 2), match_seconds=round(match_seconds, 2),
                        elapsed_seconds=round(time.perf_counter()-started, 2), eta_seconds=0)
        except Exception as exc:
            self.update(phase='error', message=str(exc))
        finally:
            self.update(running=False)

    def scan_photos(self, serial, photos, processed, errors, started, force=False):
        from .acceleration import cpu_budget
        with cpu_budget():
            return self._scan_photos(serial,photos,processed,errors,started,force)

    def _scan_photos(self, serial, photos, processed, errors, started, force=False):
        """Bulk cache reads, bounded I/O/CPU pipeline, and batched SQLite writes."""
        with self.connect() as con:
            cached = dict(con.execute('SELECT key,payload FROM features'))
            skipped = dict(con.execute('SELECT key,error FROM skipped'))
        # Retry recoverable legacy failures using the new FFmpeg path.
        skipped={k:v for k,v in skipped.items() if not v.startswith('动画超过分析上限')}
        if force:
            cached.clear()
            skipped.clear()
            # Invalidate old entries before reading. A cancelled/failed force
            # scan must not resurrect an old same-size/same-timestamp feature.
            with self.connect() as con:
                con.executemany('DELETE FROM features WHERE key=?', ((p['key'],) for p in photos))
                con.executemany('DELETE FROM skipped WHERE key=?', ((p['key'],) for p in photos))
        thumbnail_names = {p.name for p in self.thumbs.iterdir()}
        from .frame_policy import needs_refresh
        missing, skip_rows = [], []
        for p in photos:
            if self.cancel.is_set():
                return
            key = p['key']
            if key in cached and key+'.jpg' in thumbnail_names and key+'.npz' in thumbnail_names:
                feature=json.loads(cached.pop(key))
                if needs_refresh(dict(p, **feature)):
                    missing.append(p)
                else:
                    processed.append(dict(p, **feature))
            elif key in skipped:
                errors.append(dict(path=p['path'], error=skipped[key]))
            else:
                missing.append(p)
        self.update(cached=len(processed), done=len(processed)+len(errors), errors=len(errors),
                    message='批量读取手机图片并计算特征' if missing else '已加载本地特征缓存')
        del cached, thumbnail_names
        workers = min(8, max(2, (os.cpu_count() or 4)//2))
        futures = {}
        rows = []

        def extract(p, raw):
            if len(raw) != p['size']:
                raise ValueError('文件大小与媒体库不符，请刷新相册后重试')
            return vision.features(raw, self.thumbs/(p['key']+'.jpg'))

        with self.connect() as con, concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix='features') as executor:
            def drain(block=True):
                if not futures:
                    return
                done, _ = concurrent.futures.wait(futures, timeout=None if block else 0,
                                                  return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    p = futures.pop(future)
                    try:
                        feat = future.result()
                        con.execute('DELETE FROM skipped WHERE key=?', (p['key'],))
                        rows.append((p['key'], json.dumps(feat)))
                        processed.append(dict(p, **feat))
                    except Exception as exc:
                        message = str(exc)
                        errors.append(dict(p,error=message,preview=(self.thumbs/(p['key']+'.jpg')).exists()))
                    elapsed = time.perf_counter()-started
                    done_count = len(processed)+len(errors)
                    self.update(done=done_count, errors=len(errors), current=p['path'],
                                phase_seconds=round(elapsed, 1), rate=round(done_count/max(elapsed, .001), 1))
                if len(rows)+len(skip_rows) >= 32 or not futures:
                    con.executemany('INSERT OR REPLACE INTO features VALUES (?,?)', rows)
                    con.executemany('INSERT OR REPLACE INTO skipped VALUES (?,?)', skip_rows)
                    con.commit()
                    rows.clear()
                    skip_rows.clear()

            def submit(p, raw):
                while len(futures) >= workers*2:
                    drain()
                if not self.cancel.is_set():
                    futures[executor.submit(extract, p, raw)] = p
                drain(False)

            videos=[p for p in missing if p.get('media_type')=='video']
            missing=[p for p in missing if p.get('media_type')!='video']
            offset = 0
            while offset < len(missing) and not self.cancel.is_set():
                batch, size = [], 0
                while offset < len(missing) and len(batch) < 48 and size < 32*1024**2:
                    p = missing[offset]
                    batch.append(p)
                    size += p['size']
                    offset += 1
                received = set()
                stream = adb.read_batch(serial, batch)
                try:
                    while not self.cancel.is_set():
                        try:
                            p, raw = next(stream)
                        except StopIteration:
                            break
                        except Exception:
                            break  # Retry omitted files with the compatible reader.
                        submit(p, raw)
                        received.add(p['key'])
                finally:
                    stream.close()
                for p in batch:
                    if self.cancel.is_set():
                        break
                    if p['key'] in received:
                        continue
                    try:
                        raw = adb.read_photo(serial, p['path'])
                    except Exception as exc:
                        errors.append(dict(p,error=str(exc),preview=(self.thumbs/(p['key']+'.jpg')).exists()))
                    else:
                        submit(p, raw)
            while futures:
                drain()
            from .media import file_features
            for p in videos:
                if self.cancel.is_set():break
                self.update(current=p['path'],message='读取视频并提取关键帧（临时原文件处理后删除）')
                try:
                    with tempfile.TemporaryDirectory(prefix='photocluster-video-') as folder:
                        path=Path(folder)/('source'+Path(p['path']).suffix)
                        adb.pull_file(serial,p['path'],path)
                        if path.stat().st_size!=p['size']:raise ValueError('视频大小变化，请重新同步')
                        feat=file_features(path,self.thumbs/(p['key']+'.jpg'),video=True)
                    con.execute('INSERT OR REPLACE INTO features VALUES (?,?)',(p['key'],json.dumps(feat)));con.commit()
                    processed.append(dict(p,**feat))
                except Exception as exc:
                    errors.append(dict(p,error=str(exc),preview=(self.thumbs/(p['key']+'.jpg')).exists()))
                self.update(done=len(processed)+len(errors),errors=len(errors))
