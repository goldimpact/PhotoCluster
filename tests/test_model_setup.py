"""Pinned downloads never replace a model with unchecked remote bytes."""
import hashlib
import io
import json
import sys
from types import SimpleNamespace

import pytest

from scripts import setup_semantic


@pytest.mark.parametrize('valid', [False, True])
def test_download_checksum_before_loading_or_replacing(tmp_path, monkeypatch, valid):
    monkeypatch.setattr(setup_semantic, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['setup_semantic.py'])
    folder = tmp_path / 'data/models'
    folder.mkdir(parents=True)
    target = folder / 'clip-vision-int8.onnx'
    target.write_bytes(b'previous model')
    content = b'synthetic model payload'
    monkeypatch.setattr(setup_semantic, 'SHA256', hashlib.sha256(content if valid else b'other').hexdigest())
    requests = []

    def open_download(url, **kwargs):
        requests.append(url)
        return io.BytesIO(content)

    monkeypatch.setattr(setup_semantic.urllib.request, 'build_opener', lambda *args: SimpleNamespace(open=open_download))
    loaded = []
    monkeypatch.setitem(sys.modules, 'onnxruntime', SimpleNamespace(
        disable_telemetry_events=lambda: None,
        InferenceSession=lambda *args, **kwargs: loaded.append(args[0])))
    if valid:
        setup_semantic.main()
        assert target.read_bytes() == content and len(loaded) == 1
        assert json.loads((folder / 'clip-vision.json').read_text())['revision'] == setup_semantic.REVISION
    else:
        with pytest.raises(RuntimeError, match='checksum mismatch'):
            setup_semantic.main()
        assert target.read_bytes() == b'previous model' and not loaded
    assert not target.with_suffix('.download').exists()
    assert len(requests) == 1 and '/resolve/' + setup_semantic.REVISION + '/' in requests[0]
