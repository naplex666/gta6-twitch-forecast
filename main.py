"""Launch analogue quantiles; Python standard library, deterministic and offline."""
import json
import math
import os
from pathlib import Path
from datetime import datetime

LEVELS = (.05, .25, .5, .75, .95)
Z = (-1.645, -.674, 0, .674, 1.645)


def stamp(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp() / 3600


def points(rows):
    return {round(stamp(r.get('from', r.get('at')))): max(1., float(r['viewers']))
            for r in rows if r.get('viewers') is not None}


def features(series, start, platforms, unlock):
    p = series.get(start, 1.)
    recent = [v for t, v in series.items() if start - 24 <= t < start]
    older = [v for t, v in series.items() if start - 168 <= t < start - 24]
    # Ratios distinguish an already-established category from a fresh unlock.
    activity = math.log(max(recent, default=p) / p)
    established = math.log(max(sum(older) / max(1, len(older)), 1.) / p)
    text = (platforms + ' ' + unlock).lower()
    console = float('pc' not in platforms.lower())
    early = float('early-access-contaminated' in text or 'early access' in text)
    rolling = float('midnight local' in text or 'rolling' in text)
    return (math.log(p), activity, max(-8, established), console, early, rolling)


def weighted_quantile(values, tau):
    values = sorted(values)
    total = sum(w for _, w in values)
    centers = []
    acc = 0.
    for value, weight in values:
        centers.append(((acc + weight / 2) / total, value))
        acc += weight
    for i, (pos, value) in enumerate(centers):
        if tau <= pos:
            if i == 0:
                return value
            prev, old = centers[i - 1]
            return old + (value - old) * (tau - prev) / (pos - prev)
    return centers[-1][1]


def baseline(case):
    p = max(1., float(case.get('known', [{}])[0].get('viewers', 1)))
    return {'hours': [{'hour': h, 'q': [min(1e9, max(.01, round(p * math.exp(z * .15 * math.sqrt(h - 1)), 2))) for z in Z]} for h in range(2, 25)]}


def forecast_case(case, name=''):
    start = round(stamp(case['day_start']))
    p = max(1., float(case['known'][0]['viewers']))
    history = points(case.get('history_hourly') or case.get('history') or [])
    history[start] = p
    target = case.get('_platforms', 'PS5, Xbox Series')
    unlock = case.get('_unlock', case.get('notes', '') + ' midnight local rolling')
    f = features(history, start, target, unlock)
    curves = []
    for comp in case.get('comparables', []):
        if 'not a launch' in comp.get('unlock', '').lower():
            continue
        s = points(comp['hourly'])
        d = round(stamp(comp['day_start']))
        if d not in s or sum(d + h in s for h in range(24)) < 20:
            continue
        g = features(s, d, comp.get('platforms', ''), comp.get('unlock', ''))
        distance = sum(a * (x - y) ** 2 for a, x, y in zip((.2, 2., .5, 1., 1., 1.), f, g))
        weight = math.exp(-min(30, distance) / 2)
        curves.append((s, d, weight))
    if len(curves) < 4:
        return baseline(case)
    result = []
    for h in range(2, 25):
        values = [(math.log(s[d + h - 1] / s[d]), w) for s, d, w in curves if d + h - 1 in s]
        median = weighted_quantile(values, .5)
        q = [weighted_quantile(values, t) for t in LEVELS]
        # A small uncertainty floor protects against nearly identical analogues.
        spread = .07 * math.sqrt(min(h - 1, 8))
        q = [median + .95 * (v - median) + spread * z for v, z in zip(q, Z)]
        result.append({'hour': h, 'q': [round(min(1e9, max(.01, p * math.exp(max(-20, min(20, v))))), 2) for v in q]})
    return {'hours': result}


def main():
    out = Path(os.environ.get('MAKEFUN_OUTPUT_DIR', '/output'))
    out.mkdir(parents=True, exist_ok=True)
    for path in sorted(Path(os.environ.get('MAKEFUN_INPUT_DIR', '/input')).glob('*.in')):
        case = {}
        try:
            case = json.loads(path.read_text())
            answer = forecast_case(case)
            assert len(answer['hours']) == 23
            for row in answer['hours']:
                assert len(row['q']) == 5 and row['q'] == sorted(row['q'])
                assert all(math.isfinite(x) and 0 < x <= 1e9 for x in row['q'])
        except Exception:
            try:
                answer = baseline(case)
            except Exception:
                answer = baseline({})
        (out / (path.stem + '.out')).write_text(json.dumps(answer, separators=(',', ':'), allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
