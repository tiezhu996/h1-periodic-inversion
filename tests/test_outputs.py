"""周期观测反演的隐藏行为检查。

候选程序一律以 runner 身份、固定环境变量和独立进程组运行。期望参数来自确定性
数据生成器，不从候选输出反推；容差按正常噪声抖动与典型错误偏差之间取值。
"""

import csv
import json
import math
import os
import random
import signal
import subprocess
import tempfile
from pathlib import Path

ENTRY = "/app/main.py"
PYTHON = "/usr/local/bin/python3"
CANDIDATE_USER = "runner"
CANDIDATE_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "HOME": "/home/runner",
    "LANG": "C.UTF-8",
    "TZ": "UTC",
}
CALL_TIMEOUT_SEC = 30


def run_candidate(*args, timeout=CALL_TIMEOUT_SEC):
    as_root = os.getuid() == 0
    proc = subprocess.Popen(
        [PYTHON, ENTRY, *[str(a) for a in args]],
        cwd="/app",
        env=CANDIDATE_ENV,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        user=CANDIDATE_USER if as_root else None,
        group=CANDIDATE_USER if as_root else None,
        extra_groups=[] if as_root else None,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise TimeoutError(f"{ENTRY} 超过 {timeout}s")
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


def make_rows(condition, seed, span, period, amplitude, phase, offset, count):
    rng = random.Random(seed)
    if condition == "off_grid":
        times = [span * i / (count - 1) + rng.uniform(-0.20, 0.20) * span / count
                 for i in range(count)]
        times[0], times[-1] = 0.0, span
        times.sort()
    elif condition == "gap":
        left_count = count // 4
        right_count = count - left_count
        left = [0.10 * span * i / (left_count - 1) for i in range(left_count)]
        right = [0.90 * span + 0.10 * span * i / (right_count - 1) for i in range(right_count)]
        times = left + right
        times = [t + rng.uniform(-0.04, 0.04) * span / count for t in times]
        times[0], times[-1] = 0.0, span
        times.sort()
    else:
        times = [span * i / (count - 1) for i in range(count)]
    values = []
    for t in times:
        signal = amplitude * math.sin(2.0 * math.pi * t / period + phase)
        values.append(offset + signal + rng.gauss(0.0, 0.018))
    if condition == "outliers":
        chosen = rng.sample(range(8, count - 8), 8)
        for index in chosen:
            values[index] += rng.choice((-1.0, 1.0)) * rng.uniform(6.5, 10.5)
    return list(zip(times, values)), chosen if condition == "outliers" else []


def run_case(condition, seed, span, period, amplitude, phase, offset, count=100):
    rows, excluded = make_rows(condition, seed, span, period, amplitude, phase, offset, count)
    folder = Path(tempfile.mkdtemp(prefix="periodic-"))
    folder.chmod(0o755)
    case = folder / "observations.csv"
    with case.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["t", "y"])
        writer.writerows(rows)
    case.chmod(0o644)
    proc = run_candidate(case)
    assert proc.returncode == 0, f"exit={proc.returncode} stderr={proc.stderr[-500:]}"
    return json.loads(proc.stdout), excluded


def angle_error(got, want):
    return abs(math.atan2(math.sin(got - want), math.cos(got - want)))


# ---------- gate：入口与输出契约，不计分 ----------

def test_prints_json_with_six_fields():
    """「程序向标准输出写一个 JSON 对象，只含六个字段」"""
    got, _ = run_case("off_grid", 11, 70.0, 13.37, 2.0, 0.3, 1.0)
    assert set(got) == {"period_days", "amplitude", "phase_rad", "offset", "inlier_rms", "used_points"}


def test_wrong_argument_count_exits_2():
    """「参数个数不对时退出码为 2，不输出 JSON」"""
    proc = run_candidate()
    assert proc.returncode == 2
    assert proc.stdout.strip() == ""


# ---------- 难点 1：谱峰落在离散网格之间 ----------

def test_period_off_grid_case_a():
    """「主周期可能落在工具原先使用的离散搜索点之间」"""
    got, _ = run_case("off_grid", 101, 73.0, 13.37, 2.2, 0.20, 0.7, 96)
    assert abs(got["period_days"] - 13.37) / 13.37 < 5.0e-4


def test_period_off_grid_case_b():
    """「主周期可能落在工具原先使用的离散搜索点之间」"""
    got, _ = run_case("off_grid", 102, 81.0, 23.71, 1.8, -0.85, -0.4, 108)
    assert abs(got["period_days"] - 23.71) / 23.71 < 5.0e-4


def test_period_off_grid_case_c():
    """「主周期可能落在工具原先使用的离散搜索点之间」"""
    got, _ = run_case("off_grid", 103, 88.0, 36.83, 2.7, 1.10, 2.1, 116)
    assert abs(got["period_days"] - 36.83) / 36.83 < 5.0e-4


# ---------- 难点 2：长时间缺测与聚集采样 ----------

def test_gap_recovers_amplitude():
    """「中间长时间缺测时，振幅和相位仍要与完整观测一致」"""
    got, _ = run_case("gap", 201, 90.0, 180.0 / 7.0, 3.2, 0.55, 1.4, 40)
    assert abs(got["amplitude"] - 3.2) / 3.2 < 0.012


def test_gap_recovers_phase():
    """「中间长时间缺测时，振幅和相位仍要与完整观测一致」"""
    got, _ = run_case("gap", 202, 90.0, 180.0 / 8.0, 2.6, -1.15, -0.8, 40)
    assert angle_error(got["phase_rad"], -1.15) < 0.025


def test_gap_recovers_offset():
    """「中间长时间缺测时，振幅和相位仍要与完整观测一致」"""
    got, _ = run_case("gap", 203, 90.0, 180.0 / 10.0, 2.4, 0.95, 1.9, 40)
    assert abs(got["offset"] - 1.9) < 0.055


# ---------- 难点 3：少量离群观测 ----------

def test_outliers_keep_amplitude():
    """「少量明显偏离的观测不应改变主信号参数」"""
    got, _ = run_case("outliers", 301, 90.0, 180.0 / 8.0, 2.3, 0.50, -0.7, 120)
    assert abs(got["amplitude"] - 2.3) / 2.3 < 0.030


def test_outliers_keep_phase():
    """「少量明显偏离的观测不应改变主信号参数」"""
    got, _ = run_case("outliers", 302, 90.0, 180.0 / 10.0, 2.1, -0.72, 1.2, 128)
    assert angle_error(got["phase_rad"], -0.72) < 0.045


def test_outliers_do_not_inflate_rms():
    """「报告的拟合均方根误差应反映正常观测的残差」"""
    got, excluded = run_case("outliers", 303, 90.0, 180.0 / 12.0, 2.5, 1.05, 0.3, 132)
    assert got["used_points"] <= 132 - len(excluded) + 2
    assert got["inlier_rms"] < 0.070
