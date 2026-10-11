"""Read-only identification of a local service, including pre-lifecycle releases."""
import json
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler


def port_available(base):
    address = urlsplit(base)
    if address.hostname != '127.0.0.1' or not address.port:
        return False
    try:
        with socket.socket() as sock:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', address.port))
            sock.listen(1)
        return True
    except OSError:
        return False


def inspect_service(base, opener=None):
    opener = opener or build_opener(ProxyHandler({}))

    def read(path):
        with opener.open(base + path, timeout=2) as response:
            return response.read(1024 * 1024).decode('utf-8')

    try:
        data = json.loads(read('/api/runtime'))
        if (isinstance(data, dict) and data.get('application') == 'PhotoCluster'
                and isinstance(data.get('managed'), bool)
                and isinstance(data.get('stopping'), bool)
                and isinstance(data.get('workspace'), str)):
            return data
        return {'conflict': True}
    except HTTPError as exc:
        if exc.code != 404:
            return {'conflict': True}
    except (URLError, OSError) as exc:
        # Windows may time out even on an unused loopback port. A successful
        # exclusive bind distinguishes that from an unresponsive live service.
        import errno
        reason = getattr(exc, 'reason', exc)
        if isinstance(reason, ConnectionRefusedError) or getattr(reason, 'errno', None) in (errno.ECONNREFUSED, 10061):
            return None
        if port_available(base):
            return None
        return {'unavailable': True}
    except (ValueError, UnicodeError):
        return {'conflict': True}

    try:
        # A generic /api/status response is not enough to identify PhotoCluster.
        html = read('/')
        status = json.loads(read('/api/status'))
        if ('<title>PhotoCluster' in html and 'id="scanTarget"' in html
                and 'src="/app.js"' in html and isinstance(status, dict)
                and isinstance(status.get('running'), bool)):
            return {'application': 'PhotoCluster', 'legacy': True, 'managed': False,
                    'stopping': False}
    except (OSError, ValueError, UnicodeError):
        pass
    return {'conflict': True}
