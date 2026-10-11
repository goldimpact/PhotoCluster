"""Audit complementary errors in saved local identity verdicts, without inference.

Input: {"cohort": "development", "reports": {"model-policy-id": {
"complete": true, "pairs": [{"a":"a", "b":"b", "same":true,
"verdict":"SAME"}]}, ...}}. Keep real input/output in ignored data/.
All reports must describe exactly the same directed frame pairs and labels.
These voting baselines are diagnostics, never production identity guarantees.
"""
import argparse
from itertools import combinations
import json
from pathlib import Path

VERDICTS = ('SAME', 'DIFFERENT', 'UNCERTAIN')


def validate(data):
    if data.get('cohort') not in ('development', 'held_out'):
        raise ValueError('Declare development or held_out cohort explicitly')
    reports = data.get('reports', {})
    if not 2 <= len(reports) <= 16:
        raise ValueError('Provide between two and sixteen model/policy reports')
    indexed = {}
    labels = None
    for name, report in reports.items():
        if not isinstance(name, str) or not name:
            raise ValueError('Model/policy IDs must be nonempty strings')
        if report.get('complete') is not True:
            raise ValueError('Incomplete reports cannot be compared')
        pairs = {}
        for row in report['pairs']:
            a, b = row['a'], row['b']
            if not all(isinstance(x, str) and x for x in (a, b)) or a == b:
                raise ValueError('Pairs need distinct nonempty item IDs')
            key = (a, b)
            if key in pairs:
                raise ValueError('Duplicate directed pair')
            if type(row['same']) is not bool or row.get('verdict') not in VERDICTS:
                raise ValueError('Expected boolean labels and explicit verdicts')
            pairs[key] = row
        current = {key: row['same'] for key, row in pairs.items()}
        if not current or (labels is not None and current != labels):
            raise ValueError('Reports must have identical directed pairs and labels')
        labels = current
        indexed[name] = pairs
    return indexed, labels


def vote(verdicts, policy):
    yes, no = verdicts.count('SAME'), verdicts.count('DIFFERENT')
    if policy == 'any':
        return 'SAME' if yes else ('DIFFERENT' if no == len(verdicts) else 'UNCERTAIN')
    if policy == 'unanimous':
        return 'SAME' if yes == len(verdicts) else ('DIFFERENT' if no == len(verdicts) else 'UNCERTAIN')
    if policy == 'majority':
        # Abstentions never shrink the denominator or turn one vote into consensus.
        if yes > len(verdicts)/2:
            return 'SAME'
        return 'DIFFERENT' if no > len(verdicts)/2 else 'UNCERTAIN'
    raise ValueError('Unknown voting baseline')


def counts(labels, decisions):
    return dict(
        correct_accept=sum(labels[k] and v == 'SAME' for k, v in decisions.items()),
        wrong_accept=sum(not labels[k] and v == 'SAME' for k, v in decisions.items()),
        correct_reject=sum(not labels[k] and v == 'DIFFERENT' for k, v in decisions.items()),
        wrong_reject=sum(labels[k] and v == 'DIFFERENT' for k, v in decisions.items()),
        uncertain_positive=sum(labels[k] and v == 'UNCERTAIN' for k, v in decisions.items()),
        uncertain_negative=sum(not labels[k] and v == 'UNCERTAIN' for k, v in decisions.items()),
    )


def evaluate(data):
    reports, labels = validate(data)
    individual = {name: counts(labels, {k: r['verdict'] for k, r in rows.items()})
                  for name, rows in reports.items()}
    baselines = {}
    for policy in ('any', 'majority', 'unanimous'):
        decisions = {key: vote([r[key]['verdict'] for r in reports.values()], policy) for key in labels}
        baselines[policy] = counts(labels, decisions)
    overlaps = []
    for a, b in combinations(reports, 2):
        overlaps.append(dict(models=[a, b], both_wrong_accept=sum(
            not same and reports[a][key]['verdict'] == reports[b][key]['verdict'] == 'SAME'
            for key, same in labels.items())))
    unanimous_errors = [dict(a=a, b=b) for (a, b), same in labels.items()
                        if not same and all(r[(a, b)]['verdict'] == 'SAME' for r in reports.values())]
    return dict(cohort=data['cohort'], pair_count=len(labels), positives=sum(labels.values()),
                negatives=sum(not x for x in labels.values()), individual=individual,
                baselines=baselines, error_overlap=overlaps, unanimous_wrong_pairs=unanimous_errors,
                note='Voting agreement is not calibrated confidence. No weights or thresholds were fitted.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source, output = Path(args.input).resolve(), Path(args.output).resolve()
    if source == output:
        parser.error('Output must not overwrite the input')
    result = evaluate(json.loads(source.read_text('utf-8')))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps({k: result[k] for k in ('cohort', 'pair_count', 'baselines')}, indent=2))
