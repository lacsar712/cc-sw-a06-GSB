TOLERANCE_NM = 0.08


def judge(nominal: float, measured: float) -> tuple[str, str]:
    delta = abs(measured - nominal)
    if delta <= TOLERANCE_NM:
        return "合格", f"偏差 {delta:.4f} nm 在允差内"
    return "超差", f"偏差 {delta:.4f} nm 超过允差 {TOLERANCE_NM}"


def in_closed_range(value: float, lo: float, hi: float) -> bool:
    """标称波长量程按闭区间判定：边界值收下，区间外拒收。"""
    return lo <= value <= hi
