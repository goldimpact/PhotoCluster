import io
import json
from urllib.error import HTTPError, URLError

from photocluster.client import inspect_service


class Opener:
    def __init__(self, routes):
        self.routes = routes
        self.paths = []

    def open(self, url, **kwargs):
        path = url.removeprefix('http://127.0.0.1:8765')
        self.paths.append(path)
        value = self.routes[path]
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(value.encode())


def test_identifies_legacy_service_without_claiming_workspace_or_exit_control():
    opener = Opener({
        '/api/runtime': HTTPError('', 404, '', {}, None),
        '/': '<title>PhotoCluster · test</title><select id="scanTarget"></select><script src="/app.js"></script>',
        '/api/status': '{"running":false,"phase":"done"}',
    })
    result = inspect_service('http://127.0.0.1:8765', opener)
    assert result['legacy'] and not result['managed']
    assert 'workspace' not in result and 'token' not in result
    assert opener.paths == ['/api/runtime', '/', '/api/status']


def test_generic_status_endpoint_is_not_enough_to_identify_legacy():
    opener = Opener({'/api/runtime': HTTPError('', 404, '', {}, None),
                     '/': '<title>Other software</title>', '/api/status': '{"running":true}'})
    assert inspect_service('http://127.0.0.1:8765', opener) == {'conflict': True}


def test_refusal_timeout_and_invalid_responses_are_distinct(monkeypatch):
    monkeypatch.setattr('photocluster.client.port_available', lambda base: False)
    for value, expected in [(URLError(ConnectionRefusedError()), None),
                            (URLError(TimeoutError()), {'unavailable': True}),
                            ('[]', {'conflict': True}), ('not JSON', {'conflict': True})]:
        assert inspect_service('http://127.0.0.1:8765', Opener({'/api/runtime': value})) == expected


def test_timeout_on_exclusively_available_port_is_stopped(monkeypatch):
    monkeypatch.setattr('photocluster.client.port_available', lambda base: True)
    assert inspect_service('http://127.0.0.1:8765', Opener({'/api/runtime': URLError(TimeoutError())})) is None


def test_current_external_and_managed_instances_preserve_their_capabilities():
    for managed in (False, True):
        data = {'application': 'PhotoCluster', 'managed': managed, 'stopping': False, 'workspace': 'test'}
        assert inspect_service('http://127.0.0.1:8765', Opener({'/api/runtime': json.dumps(data)})) == data
