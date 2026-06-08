"""Descriptives, group comparisons, categorical tests, correlation and agreement."""

import math

import numpy as np
import pandas as pd
from scipy import stats

from ..config import get, have

from ..stats_run import (cohen_d, cramers_v, fmt_p)


def _one(roles, key):
    v = roles.get(key) or []
    return v[0] if v else None


def _groups(df, dv, group):
    out = []
    for lvl, sub in df.groupby(group, dropna=True, observed=True):
        vals = pd.to_numeric(sub[dv], errors="coerce").dropna()
        if len(vals):
            out.append((str(lvl), vals.values))
    return out


def _desc_row(name, s, robust=True, normality=True):
    n = s.dropna()
    r = {"variable": name, "n": int(len(n)), "missing": int(s.isna().sum())}
    if pd.api.types.is_numeric_dtype(n) and len(n):
        r.update({
            "mean": float(n.mean()),
            "sd": float(n.std(ddof=1)) if len(n) > 1 else None,
            "sem": float(n.std(ddof=1) / math.sqrt(len(n))) if len(n) > 1 else None,
            "min": float(n.min()), "max": float(n.max()),
            "skew": float(stats.skew(n)) if len(n) > 2 else None,
            "kurtosis": float(stats.kurtosis(n)) if len(n) > 3 else None,
            "cv": float(n.std(ddof=1) / n.mean()) if len(n) > 1 and n.mean() else None,
        })
        if robust:
            q1, med, q3 = n.quantile(.25), n.median(), n.quantile(.75)
            r.update({"q1": float(q1), "median": float(med), "q3": float(q3),
                      "iqr": float(q3 - q1),
                      "mad": float(stats.median_abs_deviation(n, scale=1.0))})
        if normality and 3 <= len(n) <= 5000:
            sp = float(stats.shapiro(n).pvalue)
            r["shapiro_p"] = sp
            r["normality_flag"] = bool(sp < 0.05)
    else:
        r["unique"] = int(n.nunique())
        top = n.value_counts().head(1)
        if len(top):
            r["mode"] = str(top.index[0])
            r["mode_n"] = int(top.iloc[0])
    return r


# ─── Descriptives ────────────────────────────────────────────────────────

def describe(df, roles, params, ctl=None):
    cols = roles.get("vars", [])
    by = params.get("by")
    robust = bool(params.get("robust", True))
    normality = bool(params.get("normality", True))
    if by and by in df.columns:
        blocks = []
        for lvl, sub in df.groupby(by, dropna=True, observed=True):
            blocks.append({"level": str(lvl),
                           "rows": [_desc_row(c, sub[c], robust, normality) for c in cols]})
        return {"kind": "grouped_table", "by": by, "blocks": blocks,
                "columns": cols}
    return {"kind": "table",
            "rows": [_desc_row(c, df[c], robust, normality) for c in cols]}


def freq(df, roles, params, ctl=None):
    out = []
    for c in roles.get("vars", []):
        s = df[c]
        vc = s.value_counts(dropna=params.get("drop_missing", False))
        if params.get("sort") == "label":
            vc = vc.sort_index()
        total = vc.sum()
        rows, cum = [], 0
        for k, v in vc.items():
            cum += v
            rows.append({"level": "missing" if pd.isna(k) else str(k), "n": int(v),
                         "pct": round(100 * v / total, 2),
                         "cum_pct": round(100 * cum / total, 2)})
        out.append({"variable": c, "rows": rows, "total": int(total)})
    return {"kind": "freq", "tables": out}


def crosstab(df, roles, params, ctl=None):
    r, c = _one(roles, "row"), _one(roles, "col")
    tab = pd.crosstab(df[r], df[c])
    pct = params.get("pct", "col")
    if pct == "row":
        shown = tab.div(tab.sum(axis=1), axis=0) * 100
    elif pct == "col":
        shown = tab.div(tab.sum(axis=0), axis=1) * 100
    elif pct == "total":
        shown = tab / tab.values.sum() * 100
    else:
        shown = None
    out = {"kind": "crosstab", "row_var": r, "col_var": c,
           "levels_row": [str(x) for x in tab.index],
           "levels_col": [str(x) for x in tab.columns],
           "counts": tab.values.tolist(),
           "percent": None if shown is None else shown.round(1).values.tolist(),
           "pct_mode": pct}
    if params.get("residuals"):
        chi2, p, dof, exp = stats.chi2_contingency(tab.values)
        out["std_residuals"] = ((tab.values - exp) / np.sqrt(exp)).round(2).tolist()
        out["chi2"] = float(chi2)
        out["p"] = float(p)
    return out


def normality_check(df, roles, params, ctl=None):
    method = params.get("method", "shapiro")
    group = _one(roles, "group")
    rows = []

    def one(name, s):
        n = pd.to_numeric(s, errors="coerce").dropna()
        r = {"variable": name, "n": int(len(n))}
        if len(n) < 3:
            r["note"] = "Too few observations."
            return r
        if method == "shapiro":
            st = stats.shapiro(n.head(5000))
            r.update(statistic=float(st.statistic), p=float(st.pvalue), test="Shapiro-Wilk")
        elif method == "dagostino":
            st = stats.normaltest(n)
            r.update(statistic=float(st.statistic), p=float(st.pvalue), test="D'Agostino K²")
        elif method == "anderson":
            a = stats.anderson(n, dist="norm")
            r.update(statistic=float(a.statistic), test="Anderson-Darling",
                     critical_5pct=float(a.critical_values[2]),
                     p=None,
                     verdict="reject" if a.statistic > a.critical_values[2] else "retain")
        else:
            st = stats.kstest(n, "norm", args=(n.mean(), n.std(ddof=1)))
            r.update(statistic=float(st.statistic), p=float(st.pvalue),
                     test="Kolmogorov-Smirnov")
        r["skew"] = float(stats.skew(n))
        r["kurtosis"] = float(stats.kurtosis(n))
        return r

    for c in roles.get("vars", []):
        if group:
            for lvl, sub in df.groupby(group, dropna=True, observed=True):
                rows.append(one(f"{c} [{lvl}]", sub[c]))
        else:
            rows.append(one(c, df[c]))
    return {"kind": "table", "rows": rows,
            "hint": "Above roughly n = 300 this test rejects departures too small to "
                    "matter. Judge from the Q-Q plot."}


def variance_check(df, roles, params, ctl=None):
    dv, group = _one(roles, "dv"), _one(roles, "group")
    arrays = [a for _, a in _groups(df, dv, group) if len(a) > 1]
    m = params.get("method", "levene")
    if m == "bartlett":
        st = stats.bartlett(*arrays); test = "Bartlett"
    elif m == "fligner":
        st = stats.fligner(*arrays); test = "Fligner-Killeen"
    elif m == "brown_forsythe":
        st = stats.levene(*arrays, center="median"); test = "Brown-Forsythe"
    else:
        st = stats.levene(*arrays, center="median"); test = "Levene (median-centred)"
    sds = [float(np.std(a, ddof=1)) for a in arrays]
    return {"kind": "single", "test": test,
            "statistic": float(st.statistic), "p": float(st.pvalue),
            "sds": sds, "sd_ratio": max(sds) / min(sds) if min(sds) else None,
            "interpretation": ("Variances differ; use Welch." if st.pvalue < 0.05
                               else "No evidence against equal variances.")}


def outlier_check(df, roles, params, ctl=None):
    from ..datasets import find_outliers
    cols = roles.get("vars", [])
    idx = find_outliers(df, cols, params.get("method", "iqr"), params.get("threshold"))
    return {"kind": "outliers", "method": params.get("method"),
            "n_flagged": len(idx), "n_total": len(df),
            "indices": idx[:500],
            "rows": df.loc[idx[:200], cols].round(4).to_dict("records") if idx else [],
            "columns": cols,
            "warning": "Flagged is not the same as wrong. Exclude only for a reason "
                       "you can state in the methods section."}


def missing_check(df, roles, params, ctl=None):
    cols = roles.get("vars") or list(df.columns)
    sub = df[cols]
    per = [{"column": c, "n_missing": int(sub[c].isna().sum()),
            "pct": round(100 * float(sub[c].isna().mean()), 2)} for c in cols]
    pat = sub.notna().astype(int).astype(str).agg("".join, axis=1).value_counts().head(20)
    return {"kind": "missing", "per_column": sorted(per, key=lambda r: -r["pct"]),
            "columns": cols, "rows_total": int(len(sub)),
            "rows_complete": int(sub.notna().all(axis=1).sum()),
            "patterns": [{"pattern": k, "n": int(v)} for k, v in pat.items()]}


def power_achieved(df, roles, params, ctl=None):
    dv, group = _one(roles, "dv"), _one(roles, "group")
    g = _groups(df, dv, group)
    alpha = float(params.get("alpha", 0.05))
    if len(g) != 2:
        return {"kind": "single", "note": "Implemented for two groups."}
    (_, a), (_, b) = g
    d = cohen_d(a, b)
    n1, n2 = len(a), len(b)
    ncp = abs(d) * math.sqrt(n1 * n2 / (n1 + n2))
    crit = stats.t.ppf(1 - alpha / 2, n1 + n2 - 2)
    power = 1 - stats.nct.cdf(crit, n1 + n2 - 2, ncp) + stats.nct.cdf(-crit, n1 + n2 - 2, ncp)
    return {"kind": "single", "effect_d": float(d), "n1": n1, "n2": n2,
            "power": float(power), "alpha": alpha,
            "caveat": "Observed power is a one-to-one function of the p value and adds "
                      "no information. Report it only if asked, and prefer the "
                      "confidence interval on the effect."}


# ─── Two groups ──────────────────────────────────────────────────────────

def _table(df, roles):
    r, c = _one(roles, "row"), _one(roles, "col")
    tab = pd.crosstab(df[r], df[c])
    return r, c, tab


def chi2(df, roles, params, ctl=None):
    r, c, tab = _table(df, roles)
    correction = bool(params.get("yates", True)) and tab.shape == (2, 2)
    st, p, dof, exp = stats.chi2_contingency(tab.values, correction=correction)
    n = int(tab.values.sum())
    res = {"kind": "categorical", "test": "Chi-square test of independence",
           "row_var": r, "col_var": c,
           "levels_row": [str(x) for x in tab.index],
           "levels_col": [str(x) for x in tab.columns],
           "counts": tab.values.tolist(),
           "expected": np.round(exp, 2).tolist(),
           "statistic": float(st), "df": int(dof), "p": float(p), "n": n,
           "yates": correction,
           "effects": {"cramers_v": cramers_v(st, n, *tab.shape)},
           "sentence": f"χ²({dof}) = {st:.2f}, {fmt_p(p)}"}
    if params.get("residuals", True):
        res["std_residuals"] = np.round((tab.values - exp) / np.sqrt(exp), 2).tolist()
    if tab.shape == (2, 2):
        a, b, c_, d = tab.values.ravel()
        res["effects"]["odds_ratio"] = float((a * d) / (b * c_)) if b * c_ else None
        r1 = a / (a + b) if a + b else np.nan
        r2 = c_ / (c_ + d) if c_ + d else np.nan
        res["effects"]["risk_ratio"] = float(r1 / r2) if r2 else None
    if (exp < 5).mean() > 0.2:
        res["warning"] = (f"{int((exp < 5).sum())} of {exp.size} expected counts are "
                          "below 5. Fisher's exact test is the safer choice.")
    return res

RUNNERS = {
    "describe": describe, "freq": freq,
    "crosstab": crosstab, "normality_check": normality_check,
    "variance_check": variance_check, "outlier_check": outlier_check,
    "missing_check": missing_check, "power_achieved": power_achieved,
    "chi2": chi2,
}
