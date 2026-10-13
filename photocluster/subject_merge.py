"""Bounded post-pass reference selection for established subject groups.

Ambiguous first-pass members suggest candidates only. Every merged member must
pass the unchanged, directed verifier against the newly selected reference.
"""
from functools import lru_cache


class Cancelled(Exception):
    pass


def consolidate(groups, proposals, verify, cancelled=lambda: False, progress=None, require_peer_support=False):
    """Return index groups; retain originals whenever evidence/budget is missing.

    proposals contains (group A, group B, member, margin), at most four per
    input media. Limit neighbors to eight, reference trials to sixteen, and
    verifier requests to 64 * media count. No dense all-library pair matrix.
    Singletons are left for the ordinary first-pass recognition workflow.
    """
    groups = [list(g) for g in groups]
    parents = list(range(len(groups)))
    edges = {}
    for a, b, witness, margin in proposals:
        if len(groups[a]) < 2 or len(groups[b]) < 2:
            continue
        key = tuple(sorted((a, b)))
        witnesses = edges.setdefault(key, {})
        witnesses[witness] = max(margin, witnesses.get(witness, -1))
        if len(witnesses) > 4:
            del witnesses[min(witnesses, key=lambda i: (witnesses[i], -i))]
    ranked = sorted(edges, key=lambda pair: (-max(edges[pair].values()), pair))
    degree = [0] * len(groups)
    selected = []
    for a, b in ranked:
        if degree[a] < 8 and degree[b] < 8:
            selected.append((a, b))
            degree[a] += 1; degree[b] += 1

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    cached = lru_cache(maxsize=8192)(verify)
    remaining = 64 * sum(map(len, groups))
    def check(a,b,done):
        nonlocal remaining
        if cancelled():raise Cancelled()
        remaining-=1
        if progress and remaining%64==0:
            progress(done,len(selected),'subject_consolidate')
        return cached(a,b)
    if progress:progress(0, len(selected), 'subject_consolidate')
    for done, edge in enumerate(selected):
        if cancelled():raise Cancelled()
        a, b = map(root, edge)
        if a != b and len(groups[a])>=2 and len(groups[b])>=2:
            members = groups[a] + groups[b]
            # Original references first, then known cross-group witnesses.
            candidates = list(dict.fromkeys([groups[a][0], groups[b][0]] +
                sorted((i for i in edges[edge] if i in members), key=lambda i: (-edges[edge][i], i))))
            # Sample throughout the union, not just its highest-quality prefix.
            slots = 16 - len(candidates)
            for k in range(slots):
                candidate = members[k * (len(members)-1) // max(1, slots-1)]
                if candidate not in candidates:candidates.append(candidate)
            best = None
            baseline = (max(len(groups[a]),len(groups[b])),sum(len(groups[i])**2 for i in (a,b)))
            for ref in candidates:
                matches = {ref}
                for member in members:
                    if cancelled():raise Cancelled()
                    if ref == member:continue
                    if remaining <= 0:
                        if progress:progress(len(selected), len(selected), 'subject_consolidate')
                        return [g for g in groups if g]
                    if check(ref, member, done) is not None:
                        matches.add(member)
                complete=len(matches)==len(members)
                if complete and require_peer_support:
                    # Two disjoint cross-group correspondences, not a single
                    # broadly matching reference, must support a complete union.
                    edges_found=[];supported=False
                    for left in groups[a]:
                        for right in groups[b]:
                            if remaining<=0:return [g for g in groups if g]
                            if check(left,right,done) is not None:
                                if any(x!=left and y!=right for x,y in edges_found):
                                    supported=True;break
                                edges_found.append((left,right))
                        if supported:break
                    complete=supported
                if complete:
                    groups[a] = [ref] + [i for i in members if i != ref]
                    groups[b] = []
                    parents[b] = a
                    best = None
                    break
                # A difficult outlier must not veto an otherwise supported core.
                # Require two distinct direct peers from the other source group.
                while True:
                    previous=set(matches)
                    if ref not in matches:break
                    sides=[[i for i in group if i in matches] for group in (groups[a],groups[b])]
                    if min(map(len,sides))<2:break
                    unsupported=set()
                    for side,other in (sides,sides[::-1]):
                        for member in side:
                            hits=0
                            for peer in other:
                                if cancelled():raise Cancelled()
                                if remaining<=0:return [g for g in groups if g]
                                hits+=check(member,peer,done) is not None
                                if hits>=2:break
                            if hits<2:unsupported.add(member)
                    matches.difference_update(unsupported)
                    if matches==previous:break
                if ref not in matches:continue
                if any(sum(i in matches for i in group)<2 for group in (groups[a],groups[b])):continue
                residuals=[[i for i in group if i not in matches] for group in (groups[a],groups[b])]
                score=(len(matches),len(matches)**2+sum(len(g)**2 for g in residuals))
                if score>baseline and (best is None or score>best[0]):
                    # Residual groups also need a verified reference. Singletons
                    # return to ungrouped media through the normal publication path.
                    valid=True
                    for n,residual in enumerate(residuals):
                        if len(residual)<2:continue
                        found=None
                        for candidate in residual[:4]:
                            accepted=True
                            for member in residual:
                                if candidate==member:continue
                                if cancelled():raise Cancelled()
                                if remaining<=0:return [g for g in groups if g]
                                if check(candidate,member,done) is None:
                                    accepted=False;break
                            if accepted:found=candidate;break
                        if found is None:valid=False;break
                        residuals[n]=[found]+[i for i in residual if i!=found]
                    if valid:best=(score,[ref]+[i for i in members if i in matches and i!=ref],residuals)
            if best is not None:
                _,core,residuals=best
                groups[a]=core
                groups[b]=residuals[1]
                if not groups[b]:parents[b]=a
                if residuals[0]:
                    parents.append(len(groups));groups.append(residuals[0])
        if progress:progress(done+1, len(selected), 'subject_consolidate')
    return [g for g in groups if g]
