#!/usr/bin/env bash
# 参考解：用 solution/app/ 下的完整实现替换 /app 里的同名入口。
# 留一法只退回对应难点的修法，其余部分保留。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
install -m 0644 "$HERE/app/main.py" /app/main.py

SKIP="${HTB_SKIP:-}" /usr/local/bin/python3 - /app/main.py <<'PY'
import os
import sys
from pathlib import Path

REVERT = {
    "difficulty_1": [
        ("""    step = 1.0 / (10.0 * span)""", """    step = 1.0 / (2.0 * span)"""),
        ("""    return refine_period(times, values, best_frequency, 1.5 * step)""", """    return 1.0 / best_frequency"""),
    ],
    "difficulty_2": [(
        """def prepare_series(times, values):
    pairs = sorted(zip(times, values))
    return [p[0] for p in pairs], [p[1] for p in pairs]""",
        """def prepare_series(times, values):
    pairs = sorted(zip(times, values))
    source_t = [p[0] for p in pairs]
    source_y = [p[1] for p in pairs]
    start = source_t[0]
    span = source_t[-1] - start
    gaps = sorted(source_t[i + 1] - source_t[i] for i in range(len(source_t) - 1))
    typical_gap = gaps[len(gaps) // 2]
    steps = 900 if gaps[-1] > 2.5 * typical_gap else len(source_t)
    uniform_t = [start + span * j / (steps - 1) for j in range(steps)]
    uniform_y = []
    cursor = 0
    for t in uniform_t:
        while cursor + 1 < len(source_t) and source_t[cursor + 1] < t:
            cursor += 1
        if cursor + 1 >= len(source_t):
            uniform_y.append(source_y[-1])
            continue
        left_t, right_t = source_t[cursor], source_t[cursor + 1]
        fraction = (t - left_t) / (right_t - left_t)
        uniform_y.append(source_y[cursor] * (1.0 - fraction) + source_y[cursor + 1] * fraction)
    return uniform_t, uniform_y""",
    )],
    "difficulty_3": [(
        """    offset, sin_coeff, cos_coeff, inlier_rms, used_points, _ = robust_fit(
        times, values, frequency
    )""",
        """    unit = [1.0] * len(times)
    offset, sin_coeff, cos_coeff, rss, _ = weighted_fit(times, values, frequency, unit)
    inlier_rms = math.sqrt(rss / len(times))
    used_points = len(times)""",
    )],
}
skip = [item for item in os.environ.get("SKIP", "").split(",") if item]
unknown = sorted(set(skip) - set(REVERT))
if unknown:
    sys.exit(f"HTB_SKIP 里有未知难点：{unknown}")
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
for key in skip:
    for fixed, original in REVERT[key]:
        if text.count(fixed) != 1:
            sys.exit(f"{key} 的修复片段在参考实现里出现 {text.count(fixed)} 次，应为 1")
        text = text.replace(fixed, original)
    print(f"留一法：{key} 退回原写法", file=sys.stderr)
path.write_text(text, encoding="utf-8")
PY
chown runner:runner /app/main.py 2>/dev/null || true
