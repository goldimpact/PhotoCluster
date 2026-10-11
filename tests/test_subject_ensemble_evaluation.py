from copy import deepcopy

import pytest

from scripts import evaluate_subject_ensemble as ensemble


def dataset():
    labels = [True, True, False, False]
    predictions = {
        'fast-v1': ['SAME', 'SAME', 'SAME', 'SAME'],
        'pair-v1': ['SAME', 'DIFFERENT', 'SAME', 'DIFFERENT'],
        'parts-v1': ['SAME', 'SAME', 'SAME', 'DIFFERENT'],
    }
    return dict(cohort='development', reports={name: dict(complete=True, pairs=[
        dict(a='reference', b=str(i), same=label, verdict=verdict)
        for i, (label, verdict) in enumerate(zip(labels, values))]) for name, values in predictions.items()})


def test_unanimous_false_positive_is_reported_not_claimed_confident():
    report = ensemble.evaluate(dataset())
    assert report['unanimous_wrong_pairs'] == [dict(a='reference', b='2')]
    assert all(x['both_wrong_accept'] == 1 for x in report['error_overlap'])
    assert report['baselines']['unanimous']['wrong_accept'] == 1
    assert report['baselines']['unanimous']['uncertain_positive'] == 1
    assert report['baselines']['majority']['correct_accept'] == 2
    for counts in [*report['individual'].values(), *report['baselines'].values()]:
        assert sum(counts.values()) == 4


@pytest.mark.parametrize('change', ['partial', 'missing_pair', 'conflicting_label', 'reverse_pair', 'duplicate', 'label_type'])
def test_mismatched_inputs_cannot_silently_select_easier_intersection(change):
    data = dataset(); report = data['reports']['parts-v1']
    if change == 'partial':report['complete'] = False
    elif change == 'missing_pair':report['pairs'].pop()
    elif change == 'conflicting_label':report['pairs'][0]['same'] = False
    elif change == 'reverse_pair':
        row = report['pairs'][0];row['a'], row['b'] = row['b'], row['a']
    elif change == 'duplicate':report['pairs'].append(deepcopy(report['pairs'][0]))
    elif change == 'label_type':report['pairs'][0]['same'] = 1
    with pytest.raises(ValueError):ensemble.evaluate(data)


def test_missing_votes_are_not_no_votes_and_do_not_strengthen_consensus():
    assert ensemble.vote(['SAME', 'UNCERTAIN', 'UNCERTAIN'], 'majority') == 'UNCERTAIN'
    assert ensemble.vote(['SAME', 'DIFFERENT'], 'majority') == 'UNCERTAIN'
    assert ensemble.vote(['DIFFERENT', 'UNCERTAIN'], 'any') == 'UNCERTAIN'
    assert ensemble.vote(['UNCERTAIN'] * 3, 'unanimous') == 'UNCERTAIN'


def test_cohort_required_and_input_unchanged():
    data = dataset(); original = deepcopy(data)
    ensemble.evaluate(data)
    assert data == original
    del data['cohort']
    with pytest.raises(ValueError, match='cohort'):ensemble.evaluate(data)
