"""Canonical options shared by the scan cache and geometry verifier."""
DEFAULT_RULES = dict(mirror=True, perspective=True, warp=False)


def normalize_rules(rules=None):
    result=dict(DEFAULT_RULES)
    if rules is not None:
        if set(rules)-set(result):raise ValueError('未知的同源识别规则')
        if any(type(value) is not bool for value in rules.values()):
            raise ValueError('识别规则必须是布尔值')
        result.update(rules)
    return result


def pair_version(rules):
    import json
    rules=normalize_rules(rules)
    # The old verifier enabled every branch. Its completed pair verdicts
    # remain valid only for precisely that combination.
    if all(rules.values()):return 'geometry-v4'
    return 'geometry-v5:'+json.dumps(rules,sort_keys=True)
