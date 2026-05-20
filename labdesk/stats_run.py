"""
Spec compilation and execution.

The browser posts {test, dataset, roles, params}. Nothing else. This module
resolves the roles against the dataset, runs the declared assumption checks,
applies the gate policy, dispatches to a runner, computes effect sizes,
formats the numbers, emits equivalent Python and R, and writes one row to
the provenance ledger.

A runner never sees a request object and never formats anything for display.
It takes (df, roles, params, ctl) and returns a plain dict.
"""
import math

from .config import get

def fmt_p(p, style=None):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "NA"
    style = style or get("stats_report_style", "apa")
    floor = get("p_min_display", 0.001)
    if p < floor:
        s = f"< {floor:g}".replace("0.", ".") if style == "apa" else f"< {floor:g}"
        return "p " + s
    d = get("p_decimals", 4)
    txt = f"{p:.{d}f}".rstrip("0").rstrip(".")
    if style == "apa" and txt.startswith("0."):
        txt = txt[1:]
    return "p = " + txt


def fmt_n(x, d=None):
    if x is None:
        return "NA"
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return "NA" if math.isnan(x) else ("∞" if x > 0 else "-∞")
    d = get("decimals", 3) if d is None else d
    return f"{x:.{d}f}"


def stars(p, thresholds=None, ns=None):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return ""
    for cutoff, mark in (thresholds or get("star_thresholds")):
        if p < cutoff:
            return mark
    return ns if ns is not None else get("ns_label", "ns")


def ci_str(lo, hi, level=None):
    level = level or get("ci_level", 0.95)
    return f"{int(level*100)}% CI [{fmt_n(lo)}, {fmt_n(hi)}]"
