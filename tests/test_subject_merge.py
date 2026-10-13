import pytest

from photocluster import subject_merge as merge


def test_common_reference_rechecks_every_member_and_does_not_mutate_input():
    groups = [[0, 1], [2, 3]]
    links = {(0, 1), (2, 3), (1, 0), (1, 2), (1, 3)}
    calls = []
    def verify(a, b):
        calls.append((a, b))
        return True if (a, b) in links else None
    result = merge.consolidate(groups, [(0, 1, 1, .9)], verify)
    assert result == [[1, 0, 2, 3]]
    assert all((1, i) in calls for i in (0, 2, 3))
    assert groups == [[0, 1], [2, 3]]


def test_matching_references_or_bridge_alone_cannot_merge_groups():
    links = {(0, 1), (2, 3), (0, 2), (2, 0), (1, 2), (1, 0)}
    groups = [[0, 1], [2, 3]]
    assert merge.consolidate(groups, [(0, 1, 1, .9)],
        lambda a, b: True if (a, b) in links else None) == groups


def test_second_merge_rechecks_entire_accumulated_group():
    groups = [[0, 1], [2, 3], [4, 5]]
    links = {(1, i) for i in (0, 2, 3)} | {(3, i) for i in (2, 4, 5)}
    result = merge.consolidate(groups, [(0, 1, 1, .9), (1, 2, 3, .8)],
        lambda a, b: True if (a, b) in links else None)
    assert result == [[1, 0, 2, 3], [4, 5]]


def test_cancellation_and_progress():
    stopped = [False]; phases = []
    def verify(a, b):
        stopped[0] = True
        return True
    with pytest.raises(merge.Cancelled):
        merge.consolidate([[0, 1], [2, 3]], [(0, 1, 1, .9)], verify,
            lambda: stopped[0], lambda *args: phases.append(args))
    assert phases == [(0, 1, 'subject_consolidate')]


def test_work_is_bounded_and_budget_exhaustion_keeps_valid_groups():
    groups = [list(range(i*20, (i+1)*20)) for i in range(30)]
    proposals = [(a, b, groups[a][1], .9) for a in range(30) for b in range(a+1, 30)]
    calls = []
    def verify(a, b):
        calls.append((a, b))
        # Each candidate fails late, exercising the overall pair-request budget.
        return True if b % 20 != 19 else None
    result = merge.consolidate(groups, proposals, verify)
    assert sorted(i for group in result for i in group)==list(range(600))
    for group in result:
        if group not in groups:
            assert all(i%20!=19 for i in group[1:])
    assert len(calls) <= 64 * 600


def test_singletons_do_not_expand_through_an_accepted_member():
    groups = [[0, 1], [2]]
    assert merge.consolidate(groups, [(0, 1, 1, .9)], lambda *args: True) == groups


def test_supported_core_can_regroup_without_outlier_veto_and_keep_residuals():
    groups=[[0,1,2,3,4],[5,6,7,8,9]]
    core={1,2,3,6,7,8};calls=[]
    def verify(a,b):
        calls.append((a,b))
        return True if (a in core and b in core) or (a,b) in ((0,4),(5,9)) else None
    result=merge.consolidate(groups,[(0,1,1,.9)],verify)
    assert sorted(map(len,result))==[2,2,6]
    assert sorted(i for group in result for i in group)==list(range(10))
    assert set(next(group for group in result if len(group)==6))==core
    for group in result:
        assert all(verify(group[0],i) for i in group[1:])


def test_partial_regroup_rejects_a_single_cross_group_bridge():
    groups=[[0,1,2,3,4],[5,6,7,8,9]]
    links={(1,i) for i in (0,2,3,5,6,7)}
    links|={(0,i) for i in (1,2,3,4)}|{(5,i) for i in (6,7,8,9)}
    result=merge.consolidate(groups,[(0,1,1,.9)],lambda a,b:True if (a,b) in links else None)
    assert result==groups


def test_supplemental_whole_merge_also_requires_distinct_cross_group_peers():
    groups=[[0,1],[2,3]]
    links={(0,1),(2,3),(0,2),(0,3),(2,0),(3,0)}
    verify=lambda a,b:True if (a,b) in links else None
    assert merge.consolidate(groups,[(0,1,0,.9)],verify)==[[0,1,2,3]]
    assert merge.consolidate(groups,[(0,1,0,.9)],verify,require_peer_support=True)==groups
    assert merge.consolidate(groups,[(0,1,0,.9)],lambda *a:True,require_peer_support=True)==[[0,1,2,3]]
