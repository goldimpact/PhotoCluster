"""Small, testable helpers for desktop preferences and bounded live logs."""
import codecs
import json
from urllib.parse import urlencode


def browser_url(base, language):
    return base + '/?' + urlencode({'lang': language if language in ('zh', 'en') else 'zh'})


def read_language(path):
    try:
        value = json.loads(path.read_text('utf-8')).get('language')
        return value if value in ('zh', 'en') else 'zh'
    except (OSError, ValueError, AttributeError):
        return 'zh'


def save_language(path, language):
    if language not in ('zh', 'en'):
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'language': language}), 'utf-8')
    except OSError:
        pass


class LogTail:
    def __init__(self, path, limit=60000):
        self.path, self.limit = path, limit
        self.offset = 0
        self.identity = None
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')

    def read(self):
        """Return (reset_display, text). Read at most limit bytes per tick."""
        try:
            with self.path.open('rb') as source:
                import os
                stat = os.fstat(source.fileno())
                identity = (stat.st_dev, stat.st_ino)
                reset = identity != self.identity or stat.st_size < self.offset
                if reset:
                    self.identity = identity
                    self.offset = max(0, stat.st_size - self.limit)
                    self.decoder.reset()
                source.seek(self.offset)
                raw = source.read(self.limit)
                self.offset += len(raw)
                return reset, self.decoder.decode(raw)
        except OSError:
            return False, ''
