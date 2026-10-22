"""周期观测反演工具。

用法：python3 /app/main.py <observations.csv>
"""

import csv
import json
import math
import sys

PERIOD_MIN = 8.0
PERIOD_MAX = 45.0
GRID_POINTS = 900
SCAN_DENSITY = 2.0
REFINE_PEAK = False
KEEP_SOURCE_TIMES = False


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


def linear_fit(times, values, frequency):
    rows = []
    for t, y in zip(times, values):
        angle = 2.0 * math.pi * frequency * t
        rows.append((1.0, math.sin(angle), math.cos(angle), y))
    normal = [[0.0] * 3 for _ in range(3)]
    rhs = [0.0] * 3
    for a, b, c, y in rows:
        basis = (a, b, c)
        for i in range(3):
            rhs[i] += basis[i] * y
            for j in range(3):
                normal[i][j] += basis[i] * basis[j]
    offset, sin_coeff, cos_coeff = solve_three(normal, rhs)
    rss = 0.0
    for t, y in zip(times, values):
        angle = 2.0 * math.pi * frequency * t
        predicted = offset + sin_coeff * math.sin(angle) + cos_coeff * math.cos(angle)
        rss += (y - predicted) ** 2
    return offset, sin_coeff, cos_coeff, rss


def read_rows(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for item in reader:
            rows.append((float(item["t"]), float(item["y"])))
    rows.sort()
    if len(rows) < 16:
        raise ValueError("not enough observations")
    return [row[0] for row in rows], [row[1] for row in rows]


def resample(times, values):
    start = times[0]
    span = times[-1] - start
    uniform_t = [start + span * j / (GRID_POINTS - 1) for j in range(GRID_POINTS)]
    uniform_y = []
    cursor = 0
    for t in uniform_t:
        while cursor + 1 < len(times) and times[cursor + 1] < t:
            cursor += 1
        if cursor + 1 >= len(times):
            uniform_y.append(values[-1])
            continue
        left_t, right_t = times[cursor], times[cursor + 1]
        fraction = (t - left_t) / (right_t - left_t)
        uniform_y.append(values[cursor] * (1.0 - fraction) + values[cursor + 1] * fraction)
    return uniform_t, uniform_y


def refine_period(times, values, center, half_width):
    left = max(1.0 / PERIOD_MAX, center - half_width)
    right = min(1.0 / PERIOD_MIN, center + half_width)
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    x1 = right - ratio * (right - left)
    x2 = left + ratio * (right - left)
    f1 = linear_fit(times, values, x1)[3]
    f2 = linear_fit(times, values, x2)[3]
    for _ in range(35):
        if f1 <= f2:
            right, x2, f2 = x2, x1, f1
            x1 = right - ratio * (right - left)
            f1 = linear_fit(times, values, x1)[3]
        else:
            left, x1, f1 = x1, x2, f2
            x2 = left + ratio * (right - left)
            f2 = linear_fit(times, values, x2)[3]
    return 1.0 / (0.5 * (left + right))


def scan_period(times, values):
    start = times[0]
    span = times[-1] - start
    low = 1.0 / PERIOD_MAX
    high = 1.0 / PERIOD_MIN
    step = 1.0 / (SCAN_DENSITY * span)
    count = int(math.floor((high - low) / step))
    best_frequency = low
    best_rss = float("inf")
    for index in range(count + 1):
        frequency = low + index * step
        try:
            _, _, _, rss = linear_fit(times, values, frequency)
        except ValueError:
            continue
        if rss < best_rss:
            best_frequency = frequency
            best_rss = rss
    if REFINE_PEAK:
        return refine_period(times, values, best_frequency, 1.5 * step)
    return 1.0 / best_frequency


def analyze(path):
    times, values = read_rows(path)
    if KEEP_SOURCE_TIMES:
        fit_times, fit_values = times, values
    else:
        fit_times, fit_values = resample(times, values)
    period = scan_period(fit_times, fit_values)
    frequency = 1.0 / period
    offset, sin_coeff, cos_coeff, rss = linear_fit(fit_times, fit_values, frequency)
    amplitude = math.hypot(sin_coeff, cos_coeff)
    phase = math.atan2(cos_coeff, sin_coeff)
    return {
        "period_days": period,
        "amplitude": amplitude,
        "phase_rad": phase,
        "offset": offset,
        "inlier_rms": math.sqrt(rss / len(fit_values)),
        "used_points": len(times),
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
