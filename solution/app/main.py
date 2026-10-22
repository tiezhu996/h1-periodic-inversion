"""周期观测反演工具。

用法：python3 /app/main.py <observations.csv>
"""

import csv
import json
import math
import sys

PERIOD_MIN = 8.0
PERIOD_MAX = 45.0


def solve_three(matrix, rhs):
    work = [list(matrix[i]) + [rhs[i]] for i in range(3)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda row: abs(work[row][col]))
        work[col], work[pivot] = work[pivot], work[col]
        scale = work[col][col]
        if abs(scale) < 1e-14:
            raise ValueError("singular normal equations")
        for j in range(col, 4):
            work[col][j] /= scale
        for row in range(3):
            if row == col:
                continue
            factor = work[row][col]
            for j in range(col, 4):
                work[row][j] -= factor * work[col][j]
    return [work[i][3] for i in range(3)]


def weighted_fit(times, values, frequency, weights):
    normal = [[0.0] * 3 for _ in range(3)]
    rhs = [0.0] * 3
    rows = []
    omega = 2.0 * math.pi * frequency
    for t, y, w in zip(times, values, weights):
        basis = (1.0, math.sin(omega * t), math.cos(omega * t))
        rows.append((basis, y))
        for i in range(3):
            rhs[i] += w * basis[i] * y
            for j in range(3):
                normal[i][j] += w * basis[i] * basis[j]
    offset, sin_coeff, cos_coeff = solve_three(normal, rhs)
    residuals = []
    rss = 0.0
    for basis, y in rows:
        predicted = offset * basis[0] + sin_coeff * basis[1] + cos_coeff * basis[2]
        residual = y - predicted
        residuals.append(residual)
        rss += residual * residual
    return offset, sin_coeff, cos_coeff, rss, residuals


def ols_rss(times, values, frequency):
    weights = [1.0] * len(times)
    return weighted_fit(times, values, frequency, weights)[3]


def median(values):
    ordered = sorted(values)
    count = len(ordered)
    if count % 2:
        return ordered[count // 2]
    return 0.5 * (ordered[count // 2 - 1] + ordered[count // 2])


def residual_scale(residuals):
    absolute = [abs(value) for value in residuals]
    scale = 1.4826 * median(absolute)
    return max(scale, 1e-7)


def robust_fit(times, values, frequency):
    count = len(times)
    weights = [1.0] * count
    result = weighted_fit(times, values, frequency, weights)
    for _ in range(10):
        scale = residual_scale(result[4])
        updated = []
        for residual in result[4]:
            size = abs(residual)
            updated.append(1.0 if size < 1.5 * scale else 1.5 * scale / size)
        change = max(abs(a - b) for a, b in zip(weights, updated))
        weights = updated
        result = weighted_fit(times, values, frequency, weights)
        if change < 1e-6:
            break
    scale = residual_scale(result[4])
    keep = [abs(residual) < 3.5 * scale for residual in result[4]]
    if sum(keep) < 12:
        keep = [True] * count
    kept_t = [t for t, flag in zip(times, keep) if flag]
    kept_y = [y for y, flag in zip(values, keep) if flag]
    unit = [1.0] * len(kept_t)
    clean = weighted_fit(kept_t, kept_y, frequency, unit)
    offset, sin_coeff, cos_coeff, rss, clean_residuals = clean
    inlier_rms = math.sqrt(rss / len(kept_y))
    return offset, sin_coeff, cos_coeff, inlier_rms, len(kept_y), clean_residuals


def prepare_series(times, values):
    pairs = sorted(zip(times, values))
    return [p[0] for p in pairs], [p[1] for p in pairs]


def robust_objective(times, values, frequency):
    return robust_fit(times, values, frequency)[3]


def refine_period(times, values, center, half_width):
    left = max(1.0 / PERIOD_MAX, center - half_width)
    right = min(1.0 / PERIOD_MIN, center + half_width)
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    x1 = right - ratio * (right - left)
    x2 = left + ratio * (right - left)
    f1 = robust_objective(times, values, x1)
    f2 = robust_objective(times, values, x2)
    for _ in range(42):
        if f1 < f2:
            right, x2, f2 = x2, x1, f1
            x1 = right - ratio * (right - left)
            f1 = robust_objective(times, values, x1)
        else:
            left, x1, f1 = x1, x2, f2
            x2 = left + ratio * (right - left)
            f2 = robust_objective(times, values, x2)
    return 1.0 / (0.5 * (left + right))


def estimate_period(times, values):
    span = times[-1] - times[0]
    low = 1.0 / PERIOD_MAX
    high = 1.0 / PERIOD_MIN
    # D1-FIX-BEGIN
    step = 1.0 / (10.0 * span)
    # D1-FIX-END
    count = int(math.floor((high - low) / step))
    scanned = []
    for index in range(count + 1):
        frequency = low + index * step
        scanned.append((ols_rss(times, values, frequency), frequency))
    scanned.sort()
    candidates = []
    for _, frequency in scanned:
        if all(abs(frequency - old) > 0.8 * step for old in candidates):
            candidates.append(frequency)
        if len(candidates) == 8:
            break
    best_frequency = min(
        candidates, key=lambda frequency: robust_objective(times, values, frequency)
    )
    # D1-REFINE-BEGIN
    return refine_period(times, values, best_frequency, 1.5 * step)
    # D1-REFINE-END


def read_rows(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        for item in csv.DictReader(handle):
            rows.append((float(item["t"]), float(item["y"])))
    if len(rows) < 16:
        raise ValueError("not enough observations")
    return prepare_series([row[0] for row in rows], [row[1] for row in rows])


def analyze(path):
    times, values = read_rows(path)
    period = estimate_period(times, values)
    frequency = 1.0 / period
    # D3-FIX-BEGIN
    offset, sin_coeff, cos_coeff, inlier_rms, used_points, _ = robust_fit(
        times, values, frequency
    )
    # D3-FIX-END
    amplitude = math.hypot(sin_coeff, cos_coeff)
    phase = math.atan2(cos_coeff, sin_coeff)
    return {
        "period_days": period,
        "amplitude": amplitude,
        "phase_rad": phase,
        "offset": offset,
        "inlier_rms": inlier_rms,
        "used_points": used_points,
    }


def main(argv):
    if len(argv) != 2:
        print("usage: python3 /app/main.py <observations.csv>", file=sys.stderr)
        return 2
    try:
        result = analyze(argv[1])
    except (OSError, KeyError, ValueError) as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
