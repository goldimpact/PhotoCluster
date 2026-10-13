import pytest

from scripts.evaluate_subject_groups import evaluate


def test_unknown_neighbors_are_not_invented_negative_labels_and_missing_are_singletons():
    data=dict(items=[dict(id='a',label='one'),dict(id='b',label='one'),dict(id='c',label='two'),dict(id='d')],
        negatives=[['a','d']],runs={'run':[['a','c','d']]})
    result=evaluate(data)['run']
    assert result['known_cross_identity_pairs']==1
    assert result['explicit_negative_pairs_merged']==1
    assert result['unlabelled_neighbor_pairs']==2
    assert result['identities']['one']==dict(total=2,largest_group=1,fragments=2,sizes=[1,1],
        retained_positive_pairs=0,possible_positive_pairs=1)


def test_reject_overlapping_snapshots_and_inconsistent_labels():
    with pytest.raises(ValueError,match='deduplicate'):
        evaluate(dict(items=[dict(id='a'),dict(id='a')],runs={}))
    with pytest.raises(ValueError,match='Conflicting'):
        evaluate(dict(items=[dict(id='a',label='same'),dict(id='b',label='same')],negatives=[['a','b']],runs={}))
    with pytest.raises(ValueError,match='multiply'):
        evaluate(dict(items=[dict(id='a')],runs={'bad':[['a'],['a']]}))


def test_positive_pair_recall_and_cross_identity_errors_are_separate():
    data=dict(items=[dict(id=k,label='one' if k!='d' else 'two') for k in 'abcd'],
        runs={'split':[['a','b'],['c','d']],'merged':[['a','b','c'],['d']]})
    result=evaluate(data)
    assert result['split']['identities']['one']['retained_positive_pairs']==1
    assert result['split']['known_cross_identity_pairs']==1
    assert result['merged']['identities']['one']['retained_positive_pairs']==3
    assert result['merged']['known_cross_identity_pairs']==0
