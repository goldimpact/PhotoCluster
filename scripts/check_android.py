"""Opt-in read-only phone smoke check. No deletion/moving or saved UI result changes.

Reads the inventory and up to one small image, GIF and video; exercises extraction,
classification, original preview and video leases in a temporary local cache.
Prints only aggregate results. Actual phone IDs, paths and hashes are not reported.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def check():
    with tempfile.TemporaryDirectory(prefix='photocluster-check-') as folder:
        os.environ['PHOTOCLUSTER_DATA_DIR'] = folder
        from photocluster import adb
        from photocluster.service import Service
        from fastapi.testclient import TestClient
        ready = [d for d in adb.devices() if d['state'] == 'device']
        if len(ready) != 1:
            raise RuntimeError('Connect exactly one authorized Android device for this check.')
        service = Service(Path(folder) / 'scan')
        inventory = service.refresh(ready[0]['serial'])
        photos = service.catalog['photos']
        categories = {
            'image': lambda p: p['path'].lower().endswith(('.jpg', '.jpeg', '.png')),
            'gif': lambda p: p['path'].lower().endswith('.gif'),
            'video': lambda p: p.get('media_type') == 'video' and p['path'].lower().endswith(('.mp4', '.webm')),
        }
        samples = {}
        for name, predicate in categories.items():
            candidates = [p for p in photos if predicate(p) and 0 < p['size'] <= 20 * 1024**2]
            if candidates:
                samples[name] = min(candidates, key=lambda p: abs(p['size'] - 300_000))
        if not samples:
            raise RuntimeError('No supported sample below 20 MB found.')
        # Check binary transfer and local paths (including WSL UNC destination).
        for photo in samples.values():
            destination = Path(folder) / ('sample with spaces' + Path(photo['path']).suffix)
            adb.pull_file(ready[0]['serial'], photo['path'], destination)
            raw = adb.read_photo(ready[0]['serial'], photo['path'])
            assert len(raw) == photo['size']
            assert hashlib.sha256(raw).digest() == hashlib.sha256(destination.read_bytes()).digest()
            destination.unlink()
        service.worker(ready[0]['serial'], list(samples.values()), 'variants', 'all')
        assert service.status['phase'] == 'done', 'Sample classification did not finish'
        analyzed = [p for g in service.result['groups'] for p in g['photos']] + service.result.get('ungrouped', [])
        assert len(analyzed) == len(samples), 'Some samples could not be analyzed'
        module = importlib.import_module('photocluster.app')
        module.service = service
        with TestClient(module.app) as client:
            assert client.get('/').status_code == 200
            assert client.get('/api/groups').status_code == 200
            for name, photo in samples.items():
                assert client.get('/api/thumb/' + photo['key']).status_code == 200
                if name == 'video':
                    response = client.post('/api/video/' + photo['key'])
                    assert response.status_code == 200, 'Video preview preparation failed'
                    lease = response.json()
                    assert client.get(lease['url'], headers={'Range': 'bytes=0-31'}).status_code == 206
                    assert client.post('/api/video-release/' + lease['token']).status_code == 200
                    assert module.video_leases.get(lease['token']) is None
                else:
                    response = client.get('/api/original/' + photo['key'])
                    assert response.status_code == 200
                    assert response.headers['cache-control'].startswith('no-store')
        return {'inventory_files': inventory['count'], 'albums': len(inventory['albums']),
                'sample_types': list(samples), 'samples_analyzed': len(analyzed),
                'binary_transfer': 'passed', 'previews': 'passed', 'phone_mutations': 0}


if __name__ == '__main__':
    try:
        print(json.dumps(check()))
    except Exception as exc:
        # Do not put raw phone paths/IDs into diagnostics intended for publication.
        print(f'Read-only check failed ({type(exc).__name__}). No phone mutation was requested.', file=sys.stderr)
        raise SystemExit(1) from None
