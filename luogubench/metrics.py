from __future__ import annotations

from collections import Counter
import math
import random
import statistics


def pearson(x, y):
    if len(x) != len(y) or len(x) < 2:
        return None
    mx, my = statistics.mean(x), statistics.mean(y)
    numerator = sum((a - mx) * (b - my) for a, b in zip(x, y))
    denominator = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return numerator / denominator if denominator else None


def ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0] * len(values)
    i = 0
    while i < len(values):
        j = i + 1
        while j < len(values) and values[order[j]] == values[order[i]]:
            j += 1
        for k in range(i, j):
            result[order[k]] = (i + 1 + j) / 2
        i = j
    return result


def spearman(x, y):
    return pearson(ranks(x), ranks(y))


def kendall_tau_b(x, y):
    concordant = discordant = ties_x = ties_y = 0
    n0 = len(x) * (len(x) - 1) // 2
    for i in range(len(x)):
        for j in range(i):
            dx, dy = x[i] - x[j], y[i] - y[j]
            ties_x += dx == 0
            ties_y += dy == 0
            concordant += dx * dy > 0
            discordant += dx * dy < 0
    denominator = math.sqrt((n0 - ties_x) * (n0 - ties_y))
    return (concordant - discordant) / denominator if denominator else None


def quadratic_weighted_kappa(x, y, levels=8):
    if not x:
        return None
    hx, hy = Counter(x), Counter(y)
    observed = sum((a - b) ** 2 for a, b in zip(x, y))
    expected = sum((a - b) ** 2 * hx[a] * hy[b] for a in range(1, levels + 1) for b in range(1, levels + 1)) / len(x)
    return 1 - observed / expected if expected else None


def summarize(actual, predicted):
    if not actual:
        raise ValueError("Cannot score an empty set")
    if len(actual) != len(predicted):
        raise ValueError("Scoring vectors must have the same length")
    errors = [p - a for a, p in zip(actual, predicted)]
    confusion = [[0 for _ in range(8)] for _ in range(8)]
    for a, p in zip(actual, predicted):
        confusion[a - 1][p - 1] += 1
    by_level = {}
    for level in sorted(set(actual)):
        pairs = [(a, p) for a, p in zip(actual, predicted) if a == level]
        by_level[str(level)] = {
            "n": len(pairs), "accuracy": sum(a == p for a, p in pairs) / len(pairs),
            "mae": statistics.mean(abs(a - p) for a, p in pairs),
            "mean_signed_error": statistics.mean(p - a for a, p in pairs),
        }
    return {
        "n": len(actual), "spearman_rho": spearman(actual, predicted),
        "kendall_tau_b": kendall_tau_b(actual, predicted), "pearson_r": pearson(actual, predicted),
        "quadratic_weighted_kappa": quadratic_weighted_kappa(actual, predicted),
        "accuracy": sum(e == 0 for e in errors) / len(errors),
        "within_one_level": sum(abs(e) <= 1 for e in errors) / len(errors),
        "exact_matches": sum(e == 0 for e in errors),
        "within_one_count": sum(abs(e) <= 1 for e in errors),
        "errors_over_one": sum(abs(e) > 1 for e in errors),
        "mae": statistics.mean(abs(e) for e in errors),
        "rmse": math.sqrt(statistics.mean(e * e for e in errors)),
        "mean_signed_error": statistics.mean(errors),
        "macro_recall": statistics.mean(v["accuracy"] for v in by_level.values()),
        "confusion_matrix": confusion, "by_level": by_level,
    }


def percentile(values, p):
    values = sorted(values)
    position = (len(values) - 1) * p
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo] * (hi - position) + values[hi] * (position - lo) if hi != lo else values[lo]


def bootstrap_spearman(actual, predicted, repetitions=2000, seed=20261113):
    rng = random.Random(seed)
    results = []
    for _ in range(repetitions):
        indices = [rng.randrange(len(actual)) for _ in actual]
        rho = spearman([actual[i] for i in indices], [predicted[i] for i in indices])
        if rho is not None:
            results.append(rho)
    return {
        "repetitions": repetitions, "seed": seed, "valid_repetitions": len(results),
        "percentile_95": [percentile(results, 0.025), percentile(results, 0.975)] if results else None,
        "interpretation": "paired item bootstrap of this curated set; not a population/generalization guarantee",
    }
