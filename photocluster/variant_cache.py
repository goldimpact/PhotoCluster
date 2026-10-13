"""Small retrieval metadata index; descriptor/image archives remain authoritative."""
from pathlib import Path
import sqlite3

import numpy as np

from .frame_policy import sampling_identity


class MetadataCache:
    def __init__(self, directory, version):
        self.directory = Path(directory)
        self.version = version
        self.con = sqlite3.connect(self.directory/'variant-index.sqlite3', timeout=30)
        self.con.execute('CREATE TABLE IF NOT EXISTS metadata ('
            'name TEXT PRIMARY KEY, sha TEXT, version INTEGER, sampling TEXT, '
            'size INTEGER, modified INTEGER, changed INTEGER, hashes BLOB, signatures BLOB)')
        self.pending = 0

    def identity(self, photo):
        path = Path(photo['feature_path']).with_suffix('.variants.npz')
        if path.parent != self.directory:return None
        try:info = path.stat()
        except FileNotFoundError:return None
        return (path.name, photo['sha256'], self.version, sampling_identity(photo),
                info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def get(self, photo):
        identity = self.identity(photo)
        if identity is None:return None
        row = self.con.execute('SELECT * FROM metadata WHERE name=?', (identity[0],)).fetchone()
        if row is None or row[:7] != identity:return None
        return dict(photo, variant_path=str(self.directory/identity[0]),
                    hashes=np.frombuffer(row[7], np.uint64).tolist(),
                    signatures=np.frombuffer(row[8], np.uint64).tolist())

    def put(self, photo, before):
        # Only index an unchanged archive whose contents prepare() validated.
        identity = self.identity(photo)
        if identity is None or identity != before:return
        self.con.execute('INSERT OR REPLACE INTO metadata VALUES (?,?,?,?,?,?,?,?,?)',
            (*identity, np.asarray(photo['hashes'], np.uint64).tobytes(),
             np.asarray(photo['signatures'], np.uint64).tobytes()))
        self.pending += 1
        if self.pending >= 64:
            self.con.commit();self.pending = 0

    def close(self):
        try:self.con.commit()
        finally:self.con.close()
