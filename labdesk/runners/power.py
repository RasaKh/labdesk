"""Power and sample size.

Every routine solves for whichever quantity is left blank, and every one
applies the dropout inflation at the end rather than silently reporting the
analysable n as if it were the recruitment target.
"""

import math

import numpy as np
from scipy import stats
from scipy.optimize import brentq


def _inflate(n, dropout):
    d = float(dropout or 0)
    return n if d <= 0 else n / (1 - d)


def _curve(fn, lo, hi, points=40):
    xs = np.linspace(lo, hi, points)
    return [{"x": float(x), "y": float(fn(x))} for x in xs]


def _power_t(n1, n2, d, alpha, tails=2):
    dof = n1 + n2 - 2
    if dof <= 0:
        return 0.0
    ncp = abs(d) * math.sqrt(n1 * n2 / (n1 + n2))
    try:
        if tails == 1:
            crit = stats.t.ppf(1 - alpha, dof)
            p = float(stats.nct.sf(crit, dof, ncp))
        else:
            crit = stats.t.ppf(1 - alpha / 2, dof)
            p = float(stats.nct.sf(crit, dof, ncp) + stats.nct.cdf(-crit, dof, ncp))
    except Exception:
        p = float("nan")
    if p != p:
        # The noncentral t is numerically unstable at large ncp. The normal
        # approximation is excellent there and never returns NaN.
        z = stats.norm.ppf(1 - alpha / (2 if tails == 2 else 1))
        p = float(stats.norm.sf(z - ncp) + (stats.norm.cdf(-z - ncp) if tails == 2 else 0))
    return max(0.0, min(1.0, p))


def _solve(fn, target, lo, hi):
    """Bracket then bisect. Avoids brentq blowing up on a NaN endpoint."""
    if fn(lo) - target > 0:
        return lo
    x = lo
    while x < hi and fn(x) - target < 0:
        x *= 2
    return brentq(lambda v: fn(v) - target, max(lo, x / 2), min(x, hi))


def power_ttest(df, roles, params, ctl=None):
    solve = params.get("solve_for", "n")
    alpha = float(params.get("alpha", 0.05))
    power = float(params.get("power", 0.8))
    d = float(params.get("effect", 0.5) or 0.5)
    ratio = float(params.get("ratio", 1.0) or 1.0)
    tails = int(params.get("tails", 2) or 2)
    n1 = params.get("n_per_group")
    dropout = float(params.get("dropout", 0) or 0)
    out = {"kind": "power", "test": "Two independent means", "solve_for": solve,
           "alpha": alpha, "tails": tails}

    if solve == "n":
        n = _solve(lambda x: _power_t(x, x * ratio, d, alpha, tails), power, 4, 1e7)
        per = math.ceil(n)
        out.update(n_per_group=per, n_group2=math.ceil(per * ratio),
                   n_total=math.ceil(per + per * ratio),
                   power=power, effect=d,
                   n_recruit_total=math.ceil(_inflate(per + per * ratio, dropout)),
                   dropout=dropout)
        out["curve"] = _curve(lambda x: _power_t(x, x * ratio, d, alpha, tails),
                              max(4, per * 0.25), per * 2.5)
        out["curve_x"] = "n per group"
        out["sentence"] = (f"{per} per group ({out['n_total']} total) gives "
                           f"{power:.0%} power to detect d = {d} at alpha {alpha}"
                           + (f". Recruit {out['n_recruit_total']} to allow for "
                              f"{dropout:.0%} dropout." if dropout else "."))
    elif solve == "power":
        n1 = int(n1 or 30)
        pw = _power_t(n1, n1 * ratio, d, alpha, tails)
        out.update(n_per_group=n1, power=float(pw), effect=d)
        out["curve"] = _curve(lambda x: _power_t(n1, n1 * ratio, x, alpha, tails), 0.05, 1.5)
        out["curve_x"] = "Cohen's d"
        out["sentence"] = f"{n1} per group gives {pw:.1%} power to detect d = {d}."
    else:
        n1 = int(n1 or 30)
        dd = brentq(lambda x: _power_t(n1, n1 * ratio, x, alpha, tails) - power, 0.001, 10)
        out.update(n_per_group=n1, power=power, effect=float(dd))
        out["curve"] = _curve(lambda x: _power_t(n1, n1 * ratio, x, alpha, tails), 0.05, 1.5)
        out["curve_x"] = "Cohen's d"
        out["sentence"] = (f"With {n1} per group the smallest detectable effect at "
                           f"{power:.0%} power is d = {dd:.3f}.")
    out["caveat"] = ("The assumed effect size should come from a prior study or a "
                     "minimum clinically important difference, not from a pilot, which "
                     "systematically overestimates it.")
    return out

RUNNERS = {
    "power_ttest": power_ttest,
}
