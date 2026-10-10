"""Native array candidate search. All Hamming-radius matches are retained."""
import numpy as np


class HammingIndex:
    def __init__(self, capacity):
        self.values = np.empty(capacity * 8, dtype=np.uint64)
        self.owners = np.empty(capacity * 8, dtype=np.int32)
        self.size = 0

    def add(self, values, index):
        unique = np.unique(np.asarray(values, dtype=np.uint64))
        end = self.size + len(unique)
        if end > len(self.values):
            capacity = max(end, max(8, len(self.values)*2))
            self.values = np.resize(self.values, capacity)
            self.owners = np.resize(self.owners, capacity)
        self.values[self.size:end] = unique
        self.owners[self.size:end] = index
        self.size = end

    def search(self, values, radius):
        if not self.size:
            return []
        found = np.zeros(self.size, dtype=bool)
        for value in set(values):
            found |= np.bitwise_count(self.values[:self.size] ^ np.uint64(value)) <= radius
        return np.unique(self.owners[:self.size][found]).tolist()


class PostingIndex:
    """Fixed-capacity active postings with the original LSH vote rules.

    Saturated buckets stop contributing after the 101st representative.
    Future images and nonrepresentative members never enter postings.
    """
    def __init__(self, photos):
        self.keys = []
        for photo in photos:
            sigs = np.asarray(photo.get('signatures', []), dtype=np.uint64)
            keys = np.unique(np.concatenate([((sigs >> (16*i)) & 65535).astype(np.int32) + i*65536 for i in range(4)]))
            self.keys.append(keys)
        # Store active representatives only. The old CSR repeatedly visited
        # future/nonrepresentative photos, then threw almost all of them away.
        # A saturated bucket never contributes again, so 100 slots suffice.
        self.postings = np.full((262144,100),-1,np.int32)
        self.counts = np.zeros(262144, np.int32)
        self.capacity = len(photos)

    def add(self, photo_index, group_index):
        keys=self.keys[photo_index]
        available=keys[self.counts[keys]<100]
        self.postings[available,self.counts[available]]=group_index
        self.counts[keys] += 1

    def search(self, photo_index, limit=16):
        keys = self.keys[photo_index]
        keys = keys[(self.counts[keys] > 0) & (self.counts[keys] <= 100)]
        if not len(keys):
            return []
        owners = self.postings[keys].ravel()
        votes = np.bincount(owners[owners >= 0], minlength=self.capacity)
        candidates = np.flatnonzero(votes >= 4)
        # Stable, deterministic tie breaking; stronger candidates come first.
        return candidates[np.argsort(-votes[candidates], kind='stable')[:limit]].tolist()
