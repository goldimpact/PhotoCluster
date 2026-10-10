from fastapi.testclient import TestClient
from photocluster.app import app


def test_api_guards():
    with TestClient(app) as client:
        assert client.get('/').status_code == 200
        assert client.get('/api/status').status_code == 200
        assert client.post('/api/scan', json={'albums':[], 'mode':'invalid'}).status_code == 422
        assert client.post('/api/operations/preview', json={'keys':['a'], 'action':'add'}).status_code == 422
        assert client.post('/api/operations/execute', json={'token':'made-up'}).status_code == 409
        assert client.post('/api/stop', json={}, headers={'Origin':'https://evil.example'}).status_code == 403
        assert client.get('/api/status', headers={'Host':'evil.example'}).status_code == 403
        assert client.get('/api/thumb/invalid').status_code == 404
