import numpy as np
import pytest

from photocluster import subject_singletons as recovery
from photocluster.subject_merge import Cancelled


def setup(n):
    photos=[dict(sha256=str(i),album='a') for i in range(n)]
    vectors={i:np.array([[1.,0.]],np.float32) for i in range(n)}
    return photos,vectors


def proof(kind='local_context'):
    return (1.,(1.,0,0),dict(kind=kind))


def test_fixed_reference_independent_peers_and_no_transitive_growth():
    photos,vectors=setup(6);groups=[[0,1,2,3],[4],[5]];calls=[]
    links={(0,4),(1,4),(2,4),(0,5),(1,5),(4,5)}
    def verify(a,b):calls.append((a,b));return proof() if (a,b) in links else None
    result=recovery.recover(groups,photos,vectors,verify)
    assert result==[[0,1,2,3,4],[5]] and (4,5) not in calls
    assert groups==[[0,1,2,3],[4],[5]]


def test_original_reference_local_evidence_required_and_ambiguity_abstains():
    photos,vectors=setup(9);groups=[[0,1,2,3],[4,5,6,7],[8]]
    assert recovery.recover(groups,photos,vectors,lambda *a:proof())==groups
    assert recovery.recover(groups,photos,vectors,lambda *a:(1.,(1.,0,0),'regions'))==groups
    assert recovery.recover(groups,photos,vectors,lambda a,b:None if a in (0,4) else proof())==groups


def test_duplicate_files_cannot_inflate_peer_support_or_target_size():
    photos,vectors=setup(6);groups=[[0,1,2,3,4],[5]]
    photos[1]['sha256']=photos[0]['sha256']
    links={(0,5),(1,5),(2,5)}
    assert recovery.recover(groups,photos,vectors,lambda a,b:proof() if (a,b) in links else None)==groups
    photos[2]['sha256']=photos[0]['sha256']
    assert recovery.recover(groups,photos,vectors,lambda *a:pytest.fail('Under four independent peers'))==groups


def test_budget_cannot_accept_before_finishing_ambiguity_review(monkeypatch):
    photos,vectors=setup(9);groups=[[0,1,2,3],[4,5,6,7],[8]];calls=[]
    # One request per media, exhausted during the later candidate check.
    monkeypatch.setattr(recovery,'MAX_VERIFY_PER_MEDIA',0)
    assert recovery.recover(groups,photos,vectors,lambda *a:calls.append(a))==groups and not calls
    # Three calls prove the first target; no budget remains to reject the second.
    monkeypatch.setattr(recovery,'MAX_VERIFY_PER_MEDIA',1/3)
    def verify(a,b):calls.append((a,b));return proof()
    assert recovery.recover(groups,photos,vectors,verify)==groups and len(calls)==3
    with pytest.raises(Cancelled):recovery.recover(groups,photos,vectors,lambda *a:proof(),cancelled=lambda:True)


def test_scope_index_budget_and_missing_features_abstain(monkeypatch):
    photos,vectors=setup(5);groups=[[0,1,2,3],[4]];photos[4]['album']='b'
    assert recovery.recover(groups,photos,vectors,lambda *a:proof(),'album')==groups
    vectors.pop(4)
    assert recovery.recover(groups,photos,vectors,lambda *a:proof())==groups
    monkeypatch.setattr(recovery,'MAX_REFERENCE_FRAMES',0)
    assert recovery.recover(groups,photos,vectors,lambda *a:proof())==groups


def test_existing_groups_never_transfer_members():
    photos,vectors=setup(6);groups=[[0,1,2,3],[4,5]]
    assert recovery.recover(groups,photos,vectors,lambda *a:pytest.fail('Only singletons'))==groups


def test_density_is_only_for_additional_identity_and_uses_frozen_target(monkeypatch):
    photos,vectors=setup(11);groups=[list(range(10)),[10]]
    def match(a,b,kind):
        accepted=(b==10 and a in (0,1,2)) or (b<10 and a!=b and (a==0 or b==0))
        return proof(kind) if accepted else None
    assert recovery.recover(groups,photos,vectors,lambda a,b:match(a,b,'local_context'))==groups
    assert recovery.recover(groups,photos,vectors,lambda a,b:match(a,b,'alternate_identity'))==[list(range(11))]
    monkeypatch.setattr(recovery,'MAX_DENSITY_PEERS',4)
    assert recovery.recover(groups,photos,vectors,lambda a,b:match(a,b,'alternate_identity'))==groups


def test_density_budget_does_not_publish_partial_statistics(monkeypatch):
    photos,vectors=setup(11);groups=[list(range(10)),[10]];calls=[]
    monkeypatch.setattr(recovery,'MAX_VERIFY_PER_MEDIA',1)
    def match(a,b):
        calls.append((a,b));return proof('alternate_identity') if b==10 and a in (0,1,2) else None
    assert recovery.recover(groups,photos,vectors,match)==groups
    assert all(b==10 for a,b in calls) and len(calls)<=11


@pytest.mark.parametrize('support,joins', [(2,False),(5,True)])
def test_density_skipped_when_support_already_decides_candidate(support,joins):
    photos,vectors=setup(11);groups=[list(range(10)),[10]];calls=[]
    def match(a,b):
        calls.append((a,b))
        assert b==10, 'No target-internal comparisons needed'
        return proof('alternate_identity') if a<support else None
    expected=[list(range(11))] if joins else groups
    assert recovery.recover(groups,photos,vectors,match)==expected
    assert len(calls)<=10


def test_deferred_density_still_checks_ambiguity_and_cancellation(monkeypatch):
    photos,vectors=setup(21);groups=[list(range(10)),list(range(10,20)),[20]]
    def match(a,b):
        accepted=a%10<3 if b==20 else (a%10==0 or b%10==0)
        return proof('alternate_identity') if accepted else None
    assert recovery.recover(groups,photos,vectors,match)==groups
    # First target qualifies after deferred density; an unfinished second
    # target must not accidentally turn that into a unique acceptance.
    monkeypatch.setattr(recovery,'MAX_VERIFY_PER_MEDIA',5)
    assert recovery.recover(groups,photos,vectors,match)==groups
    stopped=False
    def cancel_during_density(a,b):
        nonlocal stopped
        if b!=20:stopped=True
        return match(a,b)
    with pytest.raises(Cancelled):
        recovery.recover(groups,photos,vectors,cancel_during_density,cancelled=lambda:stopped)


def test_large_supported_target_needs_only_half_peer_checks():
    photos,vectors=setup(65);groups=[list(range(64)),[64]];calls=[]
    def match(a,b):
        calls.append((a,b))
        assert b==64
        return proof('alternate_identity')
    assert recovery.recover(groups,photos,vectors,match)==[list(range(65))]
    assert len(calls)==32
