"""Bounded persistent, directional geometry verdict cache; save even on stop.

Only completed comparisons are written. The cache key includes algorithm and
feature identity, SHA, dynamic/static type and normalized input path identity.
"""
import hashlib
import json
import sqlite3


class PairCache:
    def __init__(self,path,version):
        self.con=sqlite3.connect(path,timeout=30)
        self.con.execute('PRAGMA journal_mode=WAL')
        self.con.execute('CREATE TABLE IF NOT EXISTS pairs (a TEXT,b TEXT,value TEXT,PRIMARY KEY(a,b)) WITHOUT ROWID')
        self.version=version;self.pending=0;self.hits=0;self.computed=0

    def identity(self,p):
        fields=[self.version,p['sha256'],p.get('key'),bool(p.get('animated')),p.get('media_type','image')]
        return hashlib.sha256(json.dumps(fields).encode()).hexdigest()

    def query(self,sources,target):
        b=self.identity(target)
        ids=[self.identity(p) for p in sources]
        found={}
        # Stay below SQLite's parameter limit even for many hash candidates.
        for start in range(0,len(ids),500):
            chunk=ids[start:start+500]
            if not chunk:continue
            sql='SELECT a,value FROM pairs WHERE b=? AND a IN ('+','.join('?' for _ in chunk)+')'
            found.update((a,json.loads(value)) for a,value in self.con.execute(sql,[b]+chunk))
        self.hits+=sum(a in found for a in ids)
        return ids,b,found

    def save(self,ids,b,results):
        rows=[(a,b,json.dumps(result)) for a,result in zip(ids,results)]
        self.con.executemany('INSERT OR REPLACE INTO pairs VALUES (?,?,?)',rows)
        self.pending+=len(rows);self.computed+=len(rows)
        if self.pending>=256:self.con.commit();self.pending=0

    def close(self):
        excess=self.con.execute('SELECT count(*) FROM pairs').fetchone()[0]-1_000_000
        if excess>0:
            self.con.execute('DELETE FROM pairs WHERE (a,b) IN (SELECT a,b FROM pairs LIMIT ?)',(excess,))
        self.con.commit();self.con.close()
