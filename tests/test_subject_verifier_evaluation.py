import json
import os
import socket

import pytest

from scripts import evaluate_subject_verifier as evaluation


def test_manifest_rejects_remote_inputs_bad_labels_and_duplicate_ids(tmp_path):
    a = tmp_path/'a.png'; a.write_bytes(b'input')
    b = tmp_path/'b.png'; b.write_bytes(b'input')
    manifest = tmp_path/'manifest.json'
    data = dict(items=[dict(id='a', path='a.png'), dict(id='b', path='b.png')],
                pairs=[dict(a='a', b='b', same=True)])
    manifest.write_text(json.dumps(data))
    items, pairs = evaluation.read_manifest(manifest)
    assert items['a'] == a and pairs[0]['same'] is True
    for path in ('https://example.test/photo.jpg', 'file:///a.jpg', '//server/share/a.jpg', '\\\\server\\share\\a.jpg'):
        data['items'][0]['path'] = path
        manifest.write_text(json.dumps(data))
        with pytest.raises(ValueError, match='local file'):
            evaluation.read_manifest(manifest)
    data['items'][0]['path'] = 'a.png'
    data['pairs'][0]['same'] = 'false'
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='boolean'):
        evaluation.read_manifest(manifest)
    data['pairs'][0]['same'] = False
    data['items'][1]['id'] = 'a'
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='unique'):
        evaluation.read_manifest(manifest)


@pytest.mark.parametrize('answer', [
    'SAME', '{"verdict": "same"}', '{"verdict": "different"}', '{}',
    '{"verdict": "SAME"', '{"verdict": ["SAME"]}',
])
def test_malformed_or_unstructured_answer_abstains(answer):
    assert evaluation.parse_verdict(answer) == 'UNCERTAIN'


def test_valid_verdict_and_abstention_metrics():
    assert evaluation.parse_verdict('```json\n{"reason":"x", "verdict":"SAME"}\n```') == 'SAME'
    rows = [dict(same=True, verdict='SAME'), dict(same=False, verdict='SAME'),
            dict(same=True, verdict='UNCERTAIN'), dict(same=False, verdict='UNCERTAIN'),
            dict(same=False, verdict='DIFFERENT')]
    assert evaluation.metrics(rows) == dict(tp=1, fn=1, fp=1, tn=2, uncertain=2,
                                            uncertain_positive=1, uncertain_negative=1)


def test_offline_guard_blocks_connections_and_restores_on_error(monkeypatch):
    monkeypatch.setenv('HF_HUB_OFFLINE', 'before')
    previous = socket.socket.connect, socket.socket.connect_ex, socket.create_connection
    with pytest.raises(RuntimeError, match='disabled'):
        with evaluation.offline():
            assert os.environ['HF_HUB_OFFLINE'] == '1'
            socket.create_connection(('example.test', 443))
    assert os.environ['HF_HUB_OFFLINE'] == 'before'
    assert (socket.socket.connect, socket.socket.connect_ex, socket.create_connection) == previous


def test_prompt_contains_no_pair_labels_or_paths():
    content = evaluation.messages()[0]['content']
    assert sum(item['type'] == 'image' for item in content) == 2
    assert all('image' not in item for item in content)
    assert content[-1]['text'] == evaluation.PROMPT
