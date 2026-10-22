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
        ("""SCAN_DENSITY = 10.0""", """SCAN_DENSITY = 2.0"""),
        ("""REFINE_PEAK = True""", """REFINE_PEAK = False"""),
    ],
    "difficulty_2": [(
        """KEEP_SOURCE_TIMES = True""",
        """KEEP_SOURCE_TIMES = False""",
    )],
    "difficulty_3": [(
        """    offset, sin_coeff, cos_coeff, inlier_rms, used_points, _ = robust_fit(
        fit_times, fit_values, frequency
    )""",
        """    unit = [1.0] * len(fit_times)
    offset, sin_coeff, cos_coeff, rss, _ = weighted_fit(fit_times, fit_values, frequency, unit)
    inlier_rms = math.sqrt(rss / len(fit_times))
    used_points = len(fit_times)""",
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
