"""Descriptives, group comparisons, categorical tests, correlation and agreement."""

import math

import numpy as np
import pandas as pd
from scipy import stats

from .. import db
from ..config import get, have

from ..stats_run import (
    adjust_p, cles, cohen_d, cramers_v,
    d_ci, epsilon_squared, eta_squared, fmt_p,
    hedges_g, hodges_lehmann, omega_squared, rank_biserial,
)


def _one(roles, key):
    v = roles.get(key) or []
    return v[0] if v else None


def _num(df, col):
    return pd.to_numeric(df[col], errors="coerce")


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

def _two_arrays(df, roles):
    dv, group = _one(roles, "dv"), _one(roles, "group")
    g = _groups(df, dv, group)
    if len(g) != 2:
        raise ValueError(f"{group} has {len(g)} usable levels; this test needs exactly 2.")
    return dv, group, g[0], g[1]


def ttest_ind(df, roles, params, ctl=None):
    dv, group, (l1, a), (l2, b) = _two_arrays(df, roles)
    welch = bool(params.get("welch", True))
    alt = params.get("alternative", "two-sided")
    st = stats.ttest_ind(a, b, equal_var=not welch, alternative=alt)
    d = cohen_d(a, b)
    g = hedges_g(a, b)
    lo, hi = d_ci(d, len(a), len(b), params.get("ci", 0.95))
    diff = float(np.mean(a) - np.mean(b))
    se = math.sqrt(np.var(a, ddof=1) / len(a) + np.var(b, ddof=1) / len(b))
    dof = float(getattr(st, "df", len(a) + len(b) - 2))
    tcrit = stats.t.ppf(1 - (1 - params.get("ci", 0.95)) / 2, dof)
    return {
        "kind": "comparison",
        "test": "Welch t-test" if welch else "Student t-test",
        "levels": [l1, l2], "n": [len(a), len(b)],
        "mean": [float(np.mean(a)), float(np.mean(b))],
        "sd": [float(np.std(a, ddof=1)), float(np.std(b, ddof=1))],
        "statistic": float(st.statistic), "df": dof, "p": float(st.pvalue),
        "mean_diff": diff, "diff_ci": [diff - tcrit * se, diff + tcrit * se],
        "effects": {"cohen_d": d, "hedges_g": g, "d_ci": [lo, hi],
                    "cles": cles(a, b)},
        "comparisons": [{"a": l1, "b": l2, "p": float(st.pvalue)}],
        "sentence": (f"t({dof:.1f}) = {st.statistic:.2f}, {fmt_p(st.pvalue)}, "
                     f"Hedges g = {g:.2f}"),
    }


def ttest_paired(df, roles, params, ctl=None):
    a_col, b_col = _one(roles, "a"), _one(roles, "b")
    pair = df[[a_col, b_col]].apply(pd.to_numeric, errors="coerce").dropna()
    a, b = pair[a_col].values, pair[b_col].values
    st = stats.ttest_rel(a, b, alternative=params.get("alternative", "two-sided"))
    diff = a - b
    n = len(diff)
    se = diff.std(ddof=1) / math.sqrt(n)
    tcrit = stats.t.ppf(1 - (1 - params.get("ci", 0.95)) / 2, n - 1)
    dz = float(diff.mean() / diff.std(ddof=1)) if diff.std(ddof=1) else float("nan")
    return {"kind": "comparison", "test": "Paired t-test",
            "levels": [a_col, b_col], "n": [n, n],
            "mean": [float(a.mean()), float(b.mean())],
            "sd": [float(a.std(ddof=1)), float(b.std(ddof=1))],
            "statistic": float(st.statistic), "df": n - 1, "p": float(st.pvalue),
            "mean_diff": float(diff.mean()),
            "diff_ci": [float(diff.mean() - tcrit * se), float(diff.mean() + tcrit * se)],
            "effects": {"cohen_dz": dz, "hedges_g": hedges_g(a, b, paired=True)},
            "comparisons": [{"a": a_col, "b": b_col, "p": float(st.pvalue)}],
            "sentence": f"t({n-1}) = {st.statistic:.2f}, {fmt_p(st.pvalue)}, dz = {dz:.2f}"}


def ttest_1samp(df, roles, params, ctl=None):
    col = _one(roles, "dv")
    x = _num(df, col).dropna()
    mu = float(params.get("mu", 0))
    st = stats.ttest_1samp(x, mu, alternative=params.get("alternative", "two-sided"))
    se = x.std(ddof=1) / math.sqrt(len(x))
    tcrit = stats.t.ppf(1 - (1 - params.get("ci", 0.95)) / 2, len(x) - 1)
    return {"kind": "single", "test": "One-sample t-test", "variable": col,
            "n": int(len(x)), "mean": float(x.mean()), "sd": float(x.std(ddof=1)),
            "mu": mu, "statistic": float(st.statistic), "df": len(x) - 1,
            "p": float(st.pvalue),
            "mean_ci": [float(x.mean() - tcrit * se), float(x.mean() + tcrit * se)],
            "effects": {"cohen_d": float((x.mean() - mu) / x.std(ddof=1))}}


def mannwhitney(df, roles, params, ctl=None):
    dv, group, (l1, a), (l2, b) = _two_arrays(df, roles)
    st = stats.mannwhitneyu(a, b, alternative=params.get("alternative", "two-sided"),
                            use_continuity=params.get("continuity", True))
    res = {"kind": "comparison", "test": "Mann-Whitney U",
           "levels": [l1, l2], "n": [len(a), len(b)],
           "median": [float(np.median(a)), float(np.median(b))],
           "iqr": [[float(np.percentile(a, 25)), float(np.percentile(a, 75))],
                   [float(np.percentile(b, 25)), float(np.percentile(b, 75))]],
           "statistic": float(st.statistic), "p": float(st.pvalue),
           "effects": {"rank_biserial": rank_biserial(a, b), "cles": cles(a, b)},
           "comparisons": [{"a": l1, "b": l2, "p": float(st.pvalue)}]}
    if params.get("hl", True):
        res["effects"]["hodges_lehmann"] = hodges_lehmann(a, b)
    res["sentence"] = f"U = {st.statistic:.0f}, {fmt_p(st.pvalue)}"
    res["caveat"] = ("Tests whether one group tends to exceed the other. It is a test "
                     "of medians only if the two distributions have the same shape.")
    return res


def wilcoxon(df, roles, params, ctl=None):
    a_col, b_col = _one(roles, "a"), _one(roles, "b")
    pair = df[[a_col, b_col]].apply(pd.to_numeric, errors="coerce").dropna()
    a, b = pair[a_col].values, pair[b_col].values
    st = stats.wilcoxon(a, b, alternative=params.get("alternative", "two-sided"),
                        zero_method=params.get("zero_method", "wilcox"))
    return {"kind": "comparison", "test": "Wilcoxon signed-rank",
            "levels": [a_col, b_col], "n": [len(a), len(a)],
            "median": [float(np.median(a)), float(np.median(b))],
            "statistic": float(st.statistic), "p": float(st.pvalue),
            "effects": {"hodges_lehmann": hodges_lehmann(a - b)},
            "comparisons": [{"a": a_col, "b": b_col, "p": float(st.pvalue)}]}


def wilcoxon_1samp(df, roles, params, ctl=None):
    col = _one(roles, "dv")
    x = _num(df, col).dropna().values
    mu = float(params.get("mu", 0))
    st = stats.wilcoxon(x - mu, alternative=params.get("alternative", "two-sided"))
    return {"kind": "single", "test": "One-sample Wilcoxon", "variable": col,
            "n": int(len(x)), "median": float(np.median(x)), "mu": mu,
            "statistic": float(st.statistic), "p": float(st.pvalue),
            "effects": {"hodges_lehmann": hodges_lehmann(x - mu)}}


def brunner_munzel(df, roles, params, ctl=None):
    dv, group, (l1, a), (l2, b) = _two_arrays(df, roles)
    st = stats.brunnermunzel(a, b, alternative=params.get("alternative", "two-sided"))
    return {"kind": "comparison", "test": "Brunner-Munzel",
            "levels": [l1, l2], "n": [len(a), len(b)],
            "median": [float(np.median(a)), float(np.median(b))],
            "statistic": float(st.statistic), "p": float(st.pvalue),
            "effects": {"cles": cles(a, b)},
            "comparisons": [{"a": l1, "b": l2, "p": float(st.pvalue)}]}


def permutation_two(df, roles, params, ctl=None):
    dv, group, (l1, a), (l2, b) = _two_arrays(df, roles)
    n_perm = int(params.get("n_perm", 10000))
    kind = params.get("statistic", "mean_diff")
    rng = np.random.default_rng(get("seed", 0))

    def statf(x, y):
        if kind == "median_diff":
            return np.median(x) - np.median(y)
        if kind == "t":
            return stats.ttest_ind(x, y, equal_var=False).statistic
        return np.mean(x) - np.mean(y)

    obs = statf(a, b)
    pool = np.concatenate([a, b])
    n1 = len(a)
    null = np.empty(n_perm)
    for i in range(n_perm):
        if ctl and i % 500 == 0:
            ctl.check()
            ctl.progress(100 * i / n_perm, f"{i:,} of {n_perm:,} permutations")
        rng.shuffle(pool)
        null[i] = statf(pool[:n1], pool[n1:])
    alt = params.get("alternative", "two-sided")
    if alt == "greater":
        p = (np.sum(null >= obs) + 1) / (n_perm + 1)
    elif alt == "less":
        p = (np.sum(null <= obs) + 1) / (n_perm + 1)
    else:
        p = (np.sum(np.abs(null) >= abs(obs)) + 1) / (n_perm + 1)
    return {"kind": "comparison", "test": f"Permutation test ({n_perm:,} resamples)",
            "levels": [l1, l2], "n": [len(a), len(b)],
            "mean": [float(np.mean(a)), float(np.mean(b))],
            "statistic": float(obs), "p": float(p),
            "null_quantiles": [float(np.percentile(null, q)) for q in (2.5, 25, 50, 75, 97.5)],
            "null_sample": null[:2000].tolist(),
            "comparisons": [{"a": l1, "b": l2, "p": float(p)}]}


def bootstrap_diff(df, roles, params, ctl=None):
    dv, group, (l1, a), (l2, b) = _two_arrays(df, roles)
    n_boot = int(params.get("n_boot", 5000))
    level = float(params.get("ci", 0.95))
    rng = np.random.default_rng(get("seed", 0))
    kind = params.get("statistic", "mean")

    def statf(x):
        if kind == "median":
            return np.median(x)
        if kind == "trimmed_mean":
            return stats.trim_mean(x, 0.1)
        if kind == "sd":
            return np.std(x, ddof=1)
        if kind == "cv":
            return np.std(x, ddof=1) / np.mean(x) if np.mean(x) else np.nan
        return np.mean(x)

    obs = statf(a) - statf(b)
    boot = np.empty(n_boot)
    for i in range(n_boot):
        if ctl and i % 500 == 0:
            ctl.check()
            ctl.progress(100 * i / n_boot, f"{i:,} of {n_boot:,} resamples")
        boot[i] = statf(rng.choice(a, len(a), replace=True)) - \
                  statf(rng.choice(b, len(b), replace=True))
    alpha = 1 - level
    if params.get("method", "bca") == "bca":
        z0 = stats.norm.ppf(np.mean(boot < obs) or 1e-9)
        jack = np.array([statf(np.delete(a, i)) - statf(b) for i in range(len(a))] +
                        [statf(a) - statf(np.delete(b, j)) for j in range(len(b))])
        jm = jack.mean()
        num = np.sum((jm - jack) ** 3)
        den = 6 * (np.sum((jm - jack) ** 2) ** 1.5)
        acc = num / den if den else 0.0
        def adj(q):
            z = stats.norm.ppf(q)
            return stats.norm.cdf(z0 + (z0 + z) / (1 - acc * (z0 + z)))
        lo, hi = np.percentile(boot, [100 * adj(alpha / 2), 100 * adj(1 - alpha / 2)])
    else:
        lo, hi = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    p = 2 * min(np.mean(boot <= 0), np.mean(boot >= 0))
    return {"kind": "comparison", "test": f"Bootstrap difference in {kind} ({n_boot:,})",
            "levels": [l1, l2], "n": [len(a), len(b)],
            "statistic": float(obs), "diff_ci": [float(lo), float(hi)],
            "p": float(min(1, p)), "boot_sample": boot[:2000].tolist(),
            "comparisons": [{"a": l1, "b": l2, "p": float(min(1, p))}]}


# ─── Three or more groups ────────────────────────────────────────────────

def _posthoc(df, dv, group, how, correction="holm", control=None):
    """Run the named post-hoc procedure without silently substituting another.

    Dunn is implemented from pooled ranks with the standard tie correction.
    Dunnett delegates to SciPy's multivariate-t implementation and therefore
    already controls the family-wise error rate.  Nemenyi for repeated
    measures is handled in ``friedman`` below rather than here.
    """
    g = _groups(df, dv, group)
    labels = [l for l, _ in g]
    arrays = {l: np.asarray(a, dtype=float) for l, a in g}
    if len(labels) < 2:
        return [], "No pairwise comparisons"

    # A control restriction is orthogonal to the chosen test.  Only Dunnett
    # requires a control by definition; other tests can also be restricted to
    # control-vs-treatment comparisons.
    if control is not None:
        control = str(control)
        if control not in arrays:
            raise ValueError(f"Control level {control!r} was not found in {group}.")
        pairs = [(control, l) for l in labels if l != control]
    else:
        pairs = [(labels[i], labels[j])
                 for i in range(len(labels)) for j in range(i + 1, len(labels))]

    if how == "tukey":
        if control is not None:
            raise ValueError("Tukey HSD is an all-pairs procedure; use t/Welch/Dunn for control-only comparisons.")
        res = stats.tukey_hsd(*[arrays[l] for l in labels])
        rows = []
        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                a, b = arrays[labels[i]], arrays[labels[j]]
                rows.append({"a": labels[i], "b": labels[j],
                             "p_raw": float(res.pvalue[i, j]),
                             "p": float(res.pvalue[i, j]),
                             "mean_diff": float(np.mean(a) - np.mean(b)),
                             "hedges_g": hedges_g(a, b)})
        return rows, "Tukey HSD (family-wise error controlled)"

    if how == "dunnett":
        if control is None:
            raise ValueError("Dunnett's test requires a control level.")
        treatments = [l for l in labels if l != control]
        if not treatments:
            return [], "Dunnett's test"
        res = stats.dunnett(*[arrays[l] for l in treatments],
                            control=arrays[control], alternative="two-sided",
                            random_state=get("seed", 0))
        pvals = np.atleast_1d(res.pvalue)
        rows = []
        for l, pval in zip(treatments, pvals):
            a, b = arrays[control], arrays[l]
            rows.append({"a": control, "b": l, "p_raw": float(pval),
                         "p": float(pval),
                         "mean_diff": float(np.mean(a) - np.mean(b)),
                         "hedges_g": hedges_g(a, b)})
        return rows, "Dunnett's test versus control (family-wise error controlled)"

    dunn_rank_means = None
    dunn_var = None
    if how == "dunn":
        pooled = np.concatenate([arrays[l] for l in labels])
        ranks = stats.rankdata(pooled, method="average")
        N = len(pooled)
        _, tie_counts = np.unique(pooled, return_counts=True)
        tie_term = float(np.sum(tie_counts**3 - tie_counts))
        dunn_var = N * (N + 1) / 12.0
        if N > 1:
            dunn_var -= tie_term / (12.0 * (N - 1))
        dunn_rank_means = {}
        pos = 0
        for l in labels:
            n = len(arrays[l])
            dunn_rank_means[l] = float(np.mean(ranks[pos:pos+n]))
            pos += n

    # ``holm`` in the Welch-ANOVA registry means pairwise Welch tests with a
    # Holm adjustment, not a distinct statistic named "holm".
    if how == "holm":
        how = "welch"
        correction = "holm"

    rows = []
    for x, y in pairs:
        a, b = arrays[x], arrays[y]
        if how == "dunn":
            se = math.sqrt(dunn_var * (1 / len(a) + 1 / len(b)))
            zstat = ((dunn_rank_means[x] - dunn_rank_means[y]) / se
                     if se else np.nan)
            pval = 2 * stats.norm.sf(abs(zstat)) if zstat == zstat else np.nan
        elif how == "mwu":
            pval = float(stats.mannwhitneyu(a, b, alternative="two-sided").pvalue)
        elif how == "games_howell":
            n1, n2 = len(a), len(b)
            v1, v2 = a.var(ddof=1), b.var(ddof=1)
            se = math.sqrt(v1 / n1 + v2 / n2)
            t = (a.mean() - b.mean()) / se if se else np.nan
            den = ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
            dof = ((v1 / n1 + v2 / n2) ** 2 / den) if den else np.inf
            q = abs(t) * math.sqrt(2)
            pval = float(stats.studentized_range.sf(q, len(labels), dof))
        elif how in ("t", "welch"):
            pval = float(stats.ttest_ind(a, b, equal_var=(how == "t")).pvalue)
        else:
            raise ValueError(f"Unsupported post-hoc procedure {how!r}.")
        rows.append({"a": x, "b": y, "p_raw": float(pval),
                     "mean_diff": float(np.mean(a) - np.mean(b)),
                     "hedges_g": hedges_g(a, b)})

    if how == "games_howell":
        for r in rows:
            r["p"] = r["p_raw"]
        return rows, "Games-Howell (family-wise error controlled)"

    adj = adjust_p([r["p_raw"] for r in rows], correction)
    for r, v in zip(rows, adj):
        r["p"] = v
    names = {"dunn": "Dunn", "mwu": "Mann-Whitney U",
             "welch": "pairwise Welch t", "t": "pairwise t"}
    return rows, f"{names.get(how, how)} with {correction} correction"

def anova_factorial(df, roles, params, ctl=None):
    """Factorial OLS ANOVA using the factors declared by the registry."""
    if not have("statsmodels"):
        raise ValueError("Factorial ANOVA needs statsmodels.")
    import statsmodels.api as sm
    import statsmodels.formula.api as smf

    dv = _one(roles, "dv")
    factors = roles.get("factors", [])
    if len(factors) < 2:
        raise ValueError("Factorial ANOVA needs at least two factors.")
    cols = [dv] + factors
    sub = df[cols].copy()
    sub[dv] = pd.to_numeric(sub[dv], errors="coerce")
    sub = sub.dropna()
    if len(sub) <= len(factors) + 1:
        raise ValueError("Too few complete observations for factorial ANOVA.")

    qdv = f'Q("{dv}")'
    terms = [f'C(Q("{f}"))' for f in factors]
    rhs = " * ".join(terms) if params.get("interactions", True) else " + ".join(terms)
    model = smf.ols(f"{qdv} ~ {rhs}", data=sub).fit()
    typ = int(params.get("ss_type", 2))
    table = sm.stats.anova_lm(model, typ=typ)
    resid_ss = float(table.loc["Residual", "sum_sq"])
    rows = []
    for term, r in table.iterrows():
        if term == "Residual":
            rows.append({"source": "Residual", "ss": resid_ss,
                         "df": float(r["df"]), "ms": float(resid_ss / r["df"])})
            continue
        ss = float(r["sum_sq"])
        effect = ss / (ss + resid_ss) if ss + resid_ss else np.nan
        rows.append({"source": str(term), "ss": ss, "df": float(r["df"]),
                     "F": float(r["F"]), "p": float(r["PR(>F)"]),
                     "partial_eta_squared": float(effect)})

    # Plot-facing summaries use observed cells; they do not replace the model.
    cell = sub.groupby(factors, observed=True)[dv].agg(["mean", "std", "count"]).reset_index()
    cells = []
    for _, r in cell.iterrows():
        label = " × ".join(f"{f}={r[f]}" for f in factors)
        cells.append({"level": label, "mean": float(r["mean"]),
                      "sd": None if pd.isna(r["std"]) else float(r["std"]),
                      "n": int(r["count"])})
    pvals = [r.get("p") for r in rows if r.get("p") is not None]
    out = {"kind": "anova", "test": f"Factorial ANOVA (Type {typ} SS)",
           "dv": dv, "factors": factors, "n": int(len(sub)), "table": rows,
           "levels": [c["level"] for c in cells],
           "mean": [c["mean"] for c in cells],
           "sd": [c["sd"] for c in cells], "n_cells": [c["n"] for c in cells],
           "p": min(pvals) if pvals else None,
           "sentence": f"Factorial ANOVA fitted to {len(sub)} complete observations; see the term table for main effects and interactions."}
    posthoc = params.get("posthoc", "none")
    if posthoc != "none":
        tmp = sub.copy()
        tmp["__cell__"] = tmp[factors].astype(str).agg(" × ".join, axis=1)
        how = "tukey" if posthoc == "tukey" else "t"
        correction = posthoc if posthoc in ("holm", "bonferroni") else "holm"
        comps, label = _posthoc(tmp, dv, "__cell__", how, correction)
        out["comparisons"] = comps
        out["posthoc_label"] = label + " across observed factor combinations"
    return out

def anova_oneway(df, roles, params, ctl=None):
    dv, group = _one(roles, "dv"), _one(roles, "group")
    g = _groups(df, dv, group)
    arrays = [a for _, a in g]
    labels = [l for l, _ in g]
    if params.get("welch"):
        return welch_anova(df, roles, params, ctl)
    st = stats.f_oneway(*arrays)
    grand = np.concatenate(arrays)
    ss_b = sum(len(a) * (a.mean() - grand.mean()) ** 2 for a in arrays)
    ss_w = sum(((a - a.mean()) ** 2).sum() for a in arrays)
    ss_t = ss_b + ss_w
    df_b = len(arrays) - 1
    df_w = len(grand) - len(arrays)
    ms_w = ss_w / df_w if df_w else np.nan
    res = {"kind": "anova", "test": "One-way ANOVA", "dv": dv, "factor": group,
           "levels": labels, "n": [len(a) for a in arrays],
           "mean": [float(a.mean()) for a in arrays],
           "sd": [float(a.std(ddof=1)) for a in arrays],
           "sem": [float(a.std(ddof=1) / math.sqrt(len(a))) for a in arrays],
           "statistic": float(st.statistic), "df": [df_b, df_w], "p": float(st.pvalue),
           "table": [{"source": group, "ss": float(ss_b), "df": df_b,
                      "ms": float(ss_b / df_b), "F": float(st.statistic),
                      "p": float(st.pvalue)},
                     {"source": "Residual", "ss": float(ss_w), "df": df_w,
                      "ms": float(ms_w)}],
           "effects": {"eta_squared": eta_squared(ss_b, ss_t),
                       "omega_squared": omega_squared(ss_b, ss_w, df_b, ms_w, len(grand))},
           "sentence": f"F({df_b}, {df_w}) = {st.statistic:.2f}, {fmt_p(st.pvalue)}"}
    if params.get("posthoc", "tukey") != "none":
        posthoc = params.get("posthoc", "tukey")
        how = "t" if posthoc in ("holm", "bonferroni") else posthoc
        correction = posthoc if posthoc in ("holm", "bonferroni") else params.get("correction", "holm")
        rows, label = _posthoc(df, dv, group, how, correction, params.get("control"))
        res["comparisons"] = rows
        res["posthoc_label"] = label
    return res


def welch_anova(df, roles, params, ctl=None):
    dv, group = _one(roles, "dv"), _one(roles, "group")
    g = _groups(df, dv, group)
    labels = [l for l, _ in g]
    arrays = [a for _, a in g]
    k = len(arrays)
    w = np.array([len(a) / a.var(ddof=1) for a in arrays])
    m = np.array([a.mean() for a in arrays])
    n = np.array([len(a) for a in arrays])
    mw = (w * m).sum() / w.sum()
    A_ = ((w * (m - mw) ** 2).sum()) / (k - 1)
    lam = ((1 - w / w.sum()) ** 2 / (n - 1)).sum()
    B = 1 + 2 * (k - 2) / (k**2 - 1) * lam
    F = A_ / B
    df1 = k - 1
    df2 = (k**2 - 1) / (3 * lam)
    p = float(stats.f.sf(F, df1, df2))
    res = {"kind": "anova", "test": "Welch's ANOVA", "dv": dv, "factor": group,
           "levels": labels, "n": n.tolist(),
           "mean": m.tolist(),
           "sd": [float(a.std(ddof=1)) for a in arrays],
           "sem": [float(a.std(ddof=1) / math.sqrt(len(a))) for a in arrays],
           "statistic": float(F), "df": [df1, float(df2)], "p": p,
           "sentence": f"F({df1}, {df2:.1f}) = {F:.2f}, {fmt_p(p)}"}
    if params.get("posthoc", "games_howell") != "none":
        how = params.get("posthoc", "games_howell")
        if how == "holm":
            how = "welch"
        rows, label = _posthoc(df, dv, group, how, params.get("correction", "holm"))
        res["comparisons"] = rows
        res["posthoc_label"] = label
    return res


def kruskal(df, roles, params, ctl=None):
    dv, group = _one(roles, "dv"), _one(roles, "group")
    g = _groups(df, dv, group)
    arrays = [a for _, a in g]
    labels = [l for l, _ in g]
    st = stats.kruskal(*arrays)
    n = sum(len(a) for a in arrays)
    res = {"kind": "anova", "test": "Kruskal-Wallis", "dv": dv, "factor": group,
           "levels": labels, "n": [len(a) for a in arrays],
           "median": [float(np.median(a)) for a in arrays],
           "iqr": [[float(np.percentile(a, 25)), float(np.percentile(a, 75))] for a in arrays],
           "statistic": float(st.statistic), "df": [len(arrays) - 1], "p": float(st.pvalue),
           "effects": {"epsilon_squared": epsilon_squared(st.statistic, n),
                       "eta_squared_h": float((st.statistic - len(arrays) + 1) /
                                              (n - len(arrays)))},
           "sentence": f"H({len(arrays)-1}) = {st.statistic:.2f}, {fmt_p(st.pvalue)}"}
    if params.get("posthoc", "dunn") != "none":
        rows, label = _posthoc(df, dv, group, params["posthoc"],
                               params.get("correction", "holm"))
        res["comparisons"] = rows
        res["posthoc_label"] = label
    return res


def friedman(df, roles, params, ctl=None):
    dv, subj, within = _one(roles, "dv"), _one(roles, "subject"), _one(roles, "within")
    wide = df.pivot_table(index=subj, columns=within, values=dv, aggfunc="mean").dropna()
    conds = [pd.to_numeric(wide[c], errors="coerce").values for c in wide.columns]
    if len(conds) < 3 or len(wide) < 2:
        raise ValueError("Friedman needs at least three conditions and two complete subjects.")
    st = stats.friedmanchisquare(*conds)
    k = len(conds)
    n = len(wide)
    W = float(st.statistic / (n * (k - 1))) if n and k > 1 else np.nan
    res = {"kind": "anova", "test": "Friedman", "dv": dv, "factor": within,
           "levels": [str(c) for c in wide.columns], "n": [n] * k,
           "median": [float(np.median(c)) for c in conds],
           "statistic": float(st.statistic), "df": [k - 1], "p": float(st.pvalue),
           "effects": {"kendalls_w": W},
           "sentence": f"χ²({k-1}) = {st.statistic:.2f}, {fmt_p(st.pvalue)}, W = {W:.2f}"}
    posthoc = params.get("posthoc", "wilcoxon_holm")
    if posthoc == "nemenyi":
        # Nemenyi's post-Friedman test works on mean within-subject ranks and
        # uses the studentized-range distribution; no extra p adjustment is
        # applied because the procedure is already an all-pairs family test.
        rank_rows = np.apply_along_axis(stats.rankdata, 1, wide.values)
        mean_ranks = rank_rows.mean(axis=0)
        denom = math.sqrt(k * (k + 1) / (12.0 * n))
        rows = []
        cols = list(wide.columns)
        for i in range(k):
            for j in range(i + 1, k):
                q = abs(mean_ranks[i] - mean_ranks[j]) / denom if denom else np.nan
                pval = float(stats.studentized_range.sf(q, k, np.inf))
                rows.append({"a": str(cols[i]), "b": str(cols[j]),
                             "mean_rank_diff": float(mean_ranks[i] - mean_ranks[j]),
                             "p_raw": pval, "p": pval})
        res["comparisons"] = rows
        res["posthoc_label"] = "Nemenyi post-Friedman (family-wise error controlled)"
    elif posthoc == "wilcoxon_holm":
        rows = []
        cols = list(wide.columns)
        for i in range(k):
            for j in range(i + 1, k):
                pval = float(stats.wilcoxon(conds[i], conds[j]).pvalue)
                rows.append({"a": str(cols[i]), "b": str(cols[j]), "p_raw": pval})
        adj = adjust_p([r["p_raw"] for r in rows], "holm")
        for r, v in zip(rows, adj):
            r["p"] = v
        res["comparisons"] = rows
        res["posthoc_label"] = "Pairwise Wilcoxon with Holm correction"
    elif posthoc != "none":
        raise ValueError(f"Unsupported Friedman post-hoc procedure {posthoc!r}.")
    return res

def pairwise(df, roles, params, ctl=None):
    dv, group = _one(roles, "dv"), _one(roles, "group")
    how = params.get("test", "t")
    control = params.get("control") if params.get("against") == "control" else None
    # Restricting comparisons to a control must not change the selected
    # statistic. Dunnett is offered explicitly by the one-way ANOVA workflow;
    # this generic pairwise tool runs exactly the test named in its selector.
    rows, label = _posthoc(df, dv, group, how,
                           params.get("correction", "holm"), control)
    groups = _groups(df, dv, group)
    return {"kind": "pairwise", "dv": dv, "factor": group,
            "comparisons": rows, "posthoc_label": label,
            "levels": [l for l, _ in groups],
            "mean": [float(a.mean()) for _, a in groups],
            "sem": [float(a.std(ddof=1) / math.sqrt(len(a))) for _, a in groups],
            "n": [len(a) for _, a in groups]}

def padjust(df, roles, params, ctl=None):
    vals, labels = [], []
    col = (roles.get("pvals") or [None])[0]
    if col and df is not None:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        vals = s.tolist()
        labels = [str(i) for i in s.index]
    elif params.get("paste"):
        for tok in str(params["paste"]).replace("\n", ",").split(","):
            tok = tok.strip()
            if tok:
                try:
                    vals.append(float(tok))
                    labels.append(tok)
                except ValueError:
                    pass
    adj = adjust_p(vals, params.get("correction", "holm"))
    alpha = float(params.get("alpha", 0.05))
    return {"kind": "padjust", "method": params.get("correction"),
            "alpha": alpha,
            "rows": [{"label": l, "p_raw": v, "p_adj": a,
                      "significant_raw": v < alpha, "significant_adj": a < alpha}
                     for l, v, a in zip(labels, vals, adj)],
            "n_raw_sig": sum(1 for v in vals if v < alpha),
            "n_adj_sig": sum(1 for a in adj if a is not None and a < alpha)}


def multiplicity_audit(df, roles, params, ctl=None):
    from .. import datasets as ds
    alpha = float(params.get("alpha", 0.05))
    project_id = params.get("_project_id")
    runs = db.query(
        "SELECT id, test_id, created_at, status, dataset_sha FROM analysis_run "
        "WHERE project_id IS ? ORDER BY created_at DESC LIMIT 500",
        (project_id,))
    by_ds = {}
    for r in runs:
        by_ds.setdefault(r["dataset_sha"], []).append(r)
    blocks = []
    for sha, rs in by_ds.items():
        k = len([r for r in rs if r["status"] == "ok"])
        fwer = 1 - (1 - alpha) ** k if k else 0
        name = next((d["name"] for d in ds.list_datasets(project_id) if d["sha256"] == sha), sha)
        blocks.append({"dataset": name, "sha": sha, "n_runs": k,
                       "fwer": round(fwer, 4),
                       "bonferroni_alpha": round(alpha / k, 6) if k else None,
                       "tests": [r["test_id"] for r in rs[:40]]})
    return {"kind": "audit", "alpha": alpha,
            "blocks": sorted(blocks, key=lambda b: -b["n_runs"]),
            "note": "Family-wise error rate if every test on a dataset were treated as "
                    "one family at the nominal alpha. Not every run belongs to the same "
                    "family, but the count is the honest starting point."}


# ─── Categorical ─────────────────────────────────────────────────────────

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


def fisher(df, roles, params, ctl=None):
    r, c, tab = _table(df, roles)
    label = "Fisher's exact test"
    if tab.shape == (2, 2):
        odds, p = stats.fisher_exact(tab.values,
                                     alternative=params.get("alternative", "two-sided"))
    else:
        # SciPy >=1.15 provides an exact/Monte-Carlo RxC implementation.  On
        # older SciPy versions, fail explicitly rather than silently replacing
        # Fisher with a chi-square test while keeping the Fisher label.
        try:
            res = stats.fisher_exact(tab.values)
        except (TypeError, ValueError, NotImplementedError) as exc:
            raise ValueError(
                "RxC Fisher exact testing is unavailable in this SciPy build. "
                "Use the chi-square analysis explicitly; LabDesk will not silently substitute it."
            ) from exc
        odds, p = res.statistic, res.pvalue
        label = "Fisher exact test (RxC)"
    out = {"kind": "categorical", "test": label,
           "row_var": r, "col_var": c,
           "levels_row": [str(x) for x in tab.index],
           "levels_col": [str(x) for x in tab.columns],
           "counts": tab.values.tolist(), "p": float(p),
           "n": int(tab.values.sum()),
           "effects": {"odds_ratio": None if odds is None else float(odds)},
           "sentence": f"{label}, {fmt_p(p)}"}
    if tab.shape == (2, 2) and odds is not None and np.isfinite(odds) and odds > 0:
        a, b, c_, d = tab.values.ravel()
        # The simple log-OR interval is undefined with zero cells; Haldane's
        # correction is used only for the interval, not for the exact test.
        vals = np.asarray([a, b, c_, d], dtype=float)
        if np.any(vals == 0):
            vals = vals + 0.5
            or_ci_center = vals[0] * vals[3] / (vals[1] * vals[2])
        else:
            or_ci_center = float(odds)
        se = math.sqrt(np.sum(1 / vals))
        z = stats.norm.ppf(1 - (1 - get("ci_level", 0.95)) / 2)
        out["effects"]["or_ci"] = [float(math.exp(math.log(or_ci_center) - z * se)),
                                    float(math.exp(math.log(or_ci_center) + z * se))]
    return out

def mcnemar(df, roles, params, ctl=None):
    a_col, b_col = _one(roles, "a"), _one(roles, "b")
    sub = df[[a_col, b_col]].dropna()
    tab = pd.crosstab(sub[a_col], sub[b_col])
    if tab.shape != (2, 2):
        raise ValueError("McNemar needs two binary variables.")
    n01, n10 = int(tab.iloc[0, 1]), int(tab.iloc[1, 0])
    if params.get("exact", True) or (n01 + n10) < 25:
        p = float(stats.binomtest(n01, n01 + n10, 0.5).pvalue) if n01 + n10 else 1.0
        stat, test = None, "McNemar exact (binomial)"
    else:
        stat = (abs(n01 - n10) - 1) ** 2 / (n01 + n10)
        p = float(stats.chi2.sf(stat, 1))
        test = "McNemar with continuity correction"
    return {"kind": "categorical", "test": test, "row_var": a_col, "col_var": b_col,
            "levels_row": [str(x) for x in tab.index],
            "levels_col": [str(x) for x in tab.columns],
            "counts": tab.values.tolist(),
            "discordant": [n01, n10],
            "statistic": stat, "p": p, "n": int(tab.values.sum()),
            "effects": {"odds_ratio_paired": float(n01 / n10) if n10 else None},
            "sentence": f"{test}, {fmt_p(p)}"}


def cochran_q(df, roles, params, ctl=None):
    cols = roles.get("vars", [])
    sub = df[cols].dropna().astype(float)
    k = len(cols)
    n = len(sub)
    col_sums = sub.sum(axis=0).values
    row_sums = sub.sum(axis=1).values
    num = (k - 1) * (k * (col_sums**2).sum() - col_sums.sum() ** 2)
    den = k * row_sums.sum() - (row_sums**2).sum()
    Q = float(num / den) if den else np.nan
    p = float(stats.chi2.sf(Q, k - 1))
    res = {"kind": "categorical", "test": "Cochran's Q", "statistic": Q,
           "df": k - 1, "p": p, "n": n,
           "levels_col": cols, "proportions": (col_sums / n).round(4).tolist(),
           "sentence": f"Q({k-1}) = {Q:.2f}, {fmt_p(p)}"}
    if params.get("posthoc", True):
        rows = []
        for i in range(k):
            for j in range(i + 1, k):
                a, b = sub[cols[i]], sub[cols[j]]
                n01 = int(((a == 0) & (b == 1)).sum())
                n10 = int(((a == 1) & (b == 0)).sum())
                pp = float(stats.binomtest(n01, n01 + n10, 0.5).pvalue) if n01 + n10 else 1.0
                rows.append({"a": cols[i], "b": cols[j], "p_raw": pp})
        adj = adjust_p([r["p_raw"] for r in rows], params.get("correction", "holm"))
        for r, v in zip(rows, adj):
            r["p"] = v
        res["comparisons"] = rows
    return res


def armitage(df, roles, params, ctl=None):
    out_col, ord_col = _one(roles, "outcome"), _one(roles, "ordered")
    sub = df[[out_col, ord_col]].dropna()
    tab = pd.crosstab(sub[ord_col], sub[out_col])
    scores = np.arange(len(tab.index), dtype=float)
    n_i = tab.sum(axis=1).values
    r_i = tab.iloc[:, -1].values
    N = n_i.sum()
    R = r_i.sum()
    pbar = R / N
    T = float(np.sum(scores * (r_i - n_i * pbar)))
    var = pbar * (1 - pbar) * (np.sum(n_i * scores**2) - (np.sum(n_i * scores) ** 2) / N)
    z = T / math.sqrt(var) if var > 0 else np.nan
    alt = params.get("alternative", "two-sided")
    if np.isnan(z):
        p = np.nan
    elif alt == "greater":
        p = float(stats.norm.sf(z))
    elif alt == "less":
        p = float(stats.norm.cdf(z))
    else:
        p = float(2 * stats.norm.sf(abs(z)))
    return {"kind": "categorical", "test": "Cochran-Armitage trend test",
            "levels_row": [str(x) for x in tab.index],
            "counts": tab.values.tolist(),
            "proportions": (r_i / n_i).round(4).tolist(),
            "statistic": float(z), "p": p, "n": int(N),
            "sentence": f"z = {z:.2f}, {fmt_p(p)}"}


def _prop_ci(k, n, method="wilson", level=0.95):
    if n == 0:
        return (np.nan, np.nan)
    z = stats.norm.ppf(1 - (1 - level) / 2)
    p = k / n
    if method == "wald":
        se = math.sqrt(p * (1 - p) / n)
        return (p - z * se, p + z * se)
    if method == "exact":
        lo = stats.beta.ppf((1 - level) / 2, k, n - k + 1) if k else 0.0
        hi = stats.beta.ppf(1 - (1 - level) / 2, k + 1, n - k) if k < n else 1.0
        return (float(lo), float(hi))
    if method == "agresti":
        kt, nt = k + z**2 / 2, n + z**2
        pt = kt / nt
        se = math.sqrt(pt * (1 - pt) / nt)
        return (pt - z * se, pt + z * se)
    den = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / den
    return (centre - half, centre + half)


def prop_test(df, roles, params, ctl=None):
    out_col, group = _one(roles, "outcome"), _one(roles, "group")
    sub = df[[out_col, group]].dropna()
    tab = pd.crosstab(sub[group], sub[out_col])
    if tab.shape[1] != 2 or tab.shape[0] != 2:
        raise ValueError("Needs a binary outcome and exactly two groups.")
    level = float(params.get("ci", get("ci_level", 0.95)))
    method = params.get("ci_method", "wilson")
    (a, b), (c, d) = tab.values
    n1, n2 = a + b, c + d
    p1, p2 = b / n1, d / n2
    z = stats.norm.ppf(1 - (1 - level) / 2)
    eff = {}
    want = params.get("measures") or ["rr", "or", "rd", "nnt"]
    if "rr" in want and p2:
        rr = p1 / p2
        se = math.sqrt(1 / max(b, .5) - 1 / n1 + 1 / max(d, .5) - 1 / n2)
        eff["risk_ratio"] = float(rr)
        eff["rr_ci"] = [float(math.exp(math.log(rr) - z * se)),
                        float(math.exp(math.log(rr) + z * se))]
    if "or" in want and a * d:
        orr = (b * c) / (a * d)
        se = math.sqrt(sum(1 / max(v, .5) for v in (a, b, c, d)))
        eff["odds_ratio"] = float(orr)
        eff["or_ci"] = [float(math.exp(math.log(orr) - z * se)),
                        float(math.exp(math.log(orr) + z * se))]
    if "rd" in want:
        rd = p1 - p2
        se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
        eff["risk_difference"] = float(rd)
        eff["rd_ci"] = [float(rd - z * se), float(rd + z * se)]
        if "nnt" in want and rd:
            eff["nnt"] = float(1 / abs(rd))
    chi2v, p, dof, exp = stats.chi2_contingency(tab.values)
    return {"kind": "proportions", "test": "Comparison of two proportions",
            "levels": [str(x) for x in tab.index],
            "outcome_levels": [str(x) for x in tab.columns],
            "counts": tab.values.tolist(),
            "proportions": [float(p1), float(p2)],
            "prop_ci": [list(_prop_ci(b, n1, method, level)),
                        list(_prop_ci(d, n2, method, level))],
            "statistic": float(chi2v), "df": int(dof), "p": float(p),
            "effects": eff,
            "sentence": f"χ²({dof}) = {chi2v:.2f}, {fmt_p(p)}"}


def binomial(df, roles, params, ctl=None):
    col = _one(roles, "outcome")
    s = df[col].dropna()
    vals = sorted(s.unique())
    k = int((s == vals[-1]).sum())
    n = int(len(s))
    p0 = float(params.get("p0", 0.5))
    res = stats.binomtest(k, n, p0, alternative=params.get("alternative", "two-sided"))
    lo, hi = _prop_ci(k, n, "exact", float(params.get("ci", 0.95)))
    return {"kind": "single", "test": "One-sample proportion (exact)",
            "variable": col, "k": k, "n": n,
            "proportion": k / n, "ci": [lo, hi], "p0": p0, "p": float(res.pvalue)}


def goodness_fit(df, roles, params, ctl=None):
    col = _one(roles, "var")
    counts = df[col].value_counts().sort_index()
    exp_txt = (params.get("expected") or "").strip()
    if exp_txt:
        props = [float(x) for x in exp_txt.replace(" ", "").split(",")]
        expected = np.array(props) / sum(props) * counts.sum()
    else:
        expected = np.full(len(counts), counts.sum() / len(counts))
    st, p = stats.chisquare(counts.values, expected)
    return {"kind": "categorical", "test": "Chi-square goodness of fit",
            "levels_row": [str(x) for x in counts.index],
            "counts": [counts.values.tolist()],
            "expected": np.round(expected, 2).tolist(),
            "statistic": float(st), "df": len(counts) - 1, "p": float(p),
            "n": int(counts.sum()),
            "sentence": f"χ²({len(counts)-1}) = {st:.2f}, {fmt_p(p)}"}


# ─── Correlation and agreement ───────────────────────────────────────────

def correlation(df, roles, params, ctl=None):
    cols = roles.get("vars", [])
    method = params.get("method", "pearson")
    level = float(params.get("ci", get("ci_level", 0.95)))
    control = params.get("partial") or []
    if control and method == "kendall":
        raise ValueError("Partial Kendall correlation is not implemented; use Pearson or Spearman.")
    sub = df[list(dict.fromkeys(cols + list(control)))].apply(pd.to_numeric, errors="coerce")

    def residuals(y, controls):
        X = np.column_stack([np.ones(len(controls))] +
                            [controls[c].to_numpy(dtype=float) for c in control])
        beta, *_ = np.linalg.lstsq(X, y.to_numpy(dtype=float), rcond=None)
        return y.to_numpy(dtype=float) - X @ beta

    rows = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            pair = sub[[cols[i], cols[j]] + list(control)].dropna()
            if len(pair) < 3:
                continue
            x, y = pair[cols[i]], pair[cols[j]]
            if control:
                if method == "spearman":
                    ranked = pair.rank(method="average")
                    x = pd.Series(residuals(ranked[cols[i]], ranked))
                    y = pd.Series(residuals(ranked[cols[j]], ranked))
                    r, pval = stats.pearsonr(x, y)
                    ci_method = "Fisher-z approximation to partial Spearman"
                else:
                    x = pd.Series(residuals(x, pair))
                    y = pd.Series(residuals(y, pair))
                    r, pval = stats.pearsonr(x, y)
                    ci_method = "Fisher-z"
            elif method == "spearman":
                r, pval = stats.spearmanr(x, y)
                ci_method = "Fisher-z approximation"
            elif method == "kendall":
                r, pval = stats.kendalltau(x, y)
                ci_method = None
            else:
                r, pval = stats.pearsonr(x, y)
                ci_method = "Fisher-z"
            n = len(pair)
            ci = None
            if ci_method is not None:
                zval = np.arctanh(max(-0.999999, min(0.999999, r)))
                se = 1 / math.sqrt(max(1, n - 3 - len(control)))
                zc = stats.norm.ppf(1 - (1 - level) / 2)
                ci = [float(np.tanh(zval - zc * se)), float(np.tanh(zval + zc * se))]
            rows.append({"a": cols[i], "b": cols[j], "n": n, "r": float(r),
                         "p_raw": float(pval), "ci": ci, "ci_method": ci_method,
                         "r_squared": float(r**2)})
    adj = adjust_p([r["p_raw"] for r in rows], params.get("correction", "holm"))
    for r, v in zip(rows, adj):
        r["p"] = v
    mat = None
    if len(cols) > 2 and not control:
        m = sub[cols].corr(method=method)
        mat = {"labels": cols, "values": np.round(m.values, 4).tolist()}
    return {"kind": "correlation", "method": method, "rows": rows, "matrix": mat,
            "partial_on": list(control),
            "sentence": (f"r = {rows[0]['r']:.2f}, {fmt_p(rows[0]['p'])}" if rows else "")}

def icc(df, roles, params, ctl=None):
    subj, rater, val = _one(roles, "subject"), _one(roles, "rater"), _one(roles, "value")
    wide = df.pivot_table(index=subj, columns=rater, values=val, aggfunc="mean").dropna()
    n, k = wide.shape
    x = wide.values
    grand = x.mean()
    ms_r = k * ((x.mean(axis=1) - grand) ** 2).sum() / (n - 1)
    ms_c = n * ((x.mean(axis=0) - grand) ** 2).sum() / (k - 1)
    ms_e = ((x - x.mean(axis=1, keepdims=True) - x.mean(axis=0, keepdims=True)
             + grand) ** 2).sum() / ((n - 1) * (k - 1))
    ms_w = ((x - x.mean(axis=1, keepdims=True)) ** 2).sum() / (n * (k - 1))
    forms = {
        "ICC1": (ms_r - ms_w) / (ms_r + (k - 1) * ms_w),
        "ICC2": (ms_r - ms_e) / (ms_r + (k - 1) * ms_e + k * (ms_c - ms_e) / n),
        "ICC3": (ms_r - ms_e) / (ms_r + (k - 1) * ms_e),
        "ICC1k": (ms_r - ms_w) / ms_r,
        "ICC2k": (ms_r - ms_e) / (ms_r + (ms_c - ms_e) / n),
        "ICC3k": (ms_r - ms_e) / ms_r,
    }
    chosen = params.get("form", "ICC2k")
    v = float(forms.get(chosen, np.nan))
    band = ("poor" if v < 0.5 else "moderate" if v < 0.75 else
            "good" if v < 0.9 else "excellent")
    return {"kind": "icc", "form": chosen, "value": v, "n_subjects": int(n),
            "n_raters": int(k),
            "all_forms": {k2: float(v2) for k2, v2 in forms.items()},
            "interpretation": f"{band} reliability (Koo and Li bands)",
            "note": "State the form in the manuscript. ICC alone is ambiguous."}


def bland_altman(df, roles, params, ctl=None):
    a_col, b_col = _one(roles, "a"), _one(roles, "b")
    pair = df[[a_col, b_col]].apply(pd.to_numeric, errors="coerce").dropna()
    a, b = pair[a_col].values, pair[b_col].values
    diff = a - b
    mean = (a + b) / 2
    bias = float(diff.mean())
    sd = float(diff.std(ddof=1))
    k = float(params.get("loa", 1.96))
    n = len(diff)
    level = float(params.get("ci", get("ci_level", 0.95)))
    t = stats.t.ppf(1 - (1 - level) / 2, n - 1)
    se_bias = sd / math.sqrt(n)
    se_loa = sd * math.sqrt(3 / n)
    out = {"kind": "bland_altman", "n": n, "bias": bias, "sd_diff": sd,
           "loa": [bias - k * sd, bias + k * sd],
           "bias_ci": [bias - t * se_bias, bias + t * se_bias],
           "loa_lower_ci": [bias - k * sd - t * se_loa, bias - k * sd + t * se_loa],
           "loa_upper_ci": [bias + k * sd - t * se_loa, bias + k * sd + t * se_loa],
           "means": mean.tolist()[:5000], "diffs": diff.tolist()[:5000],
           "labels": [a_col, b_col]}
    if params.get("proportional", True):
        sl, ic, r, p, se = stats.linregress(mean, diff)
        out["proportional_bias"] = {"slope": float(sl), "p": float(p),
                                    "note": ("Difference varies with magnitude; "
                                             "consider a ratio or log analysis."
                                             if p < 0.05 else "No proportional bias.")}
    return out


def kappa(df, roles, params, ctl=None):
    cols = roles.get("raters", [])
    sub = df[cols].dropna()
    level = float(params.get("ci", get("ci_level", 0.95)))
    if len(cols) == 2:
        a, b = sub[cols[0]].astype(str), sub[cols[1]].astype(str)
        cats = sorted(set(a) | set(b))
        tab = pd.crosstab(a, b).reindex(index=cats, columns=cats, fill_value=0).values
        n = tab.sum()
        w = np.zeros_like(tab, dtype=float)
        kind = params.get("weights", "none")
        for i in range(len(cats)):
            for j in range(len(cats)):
                if kind == "linear":
                    w[i, j] = 1 - abs(i - j) / (len(cats) - 1)
                elif kind == "quadratic":
                    w[i, j] = 1 - ((i - j) / (len(cats) - 1)) ** 2
                else:
                    w[i, j] = 1.0 if i == j else 0.0
        po = (w * tab).sum() / n
        rows_m = tab.sum(axis=1) / n
        cols_m = tab.sum(axis=0) / n
        pe = (w * np.outer(rows_m, cols_m)).sum()
        kap = (po - pe) / (1 - pe) if pe != 1 else np.nan
        se = math.sqrt(po * (1 - po) / (n * (1 - pe) ** 2)) if pe != 1 else np.nan
        z = stats.norm.ppf(1 - (1 - level) / 2)
        val, ci = float(kap), [float(kap - z * se), float(kap + z * se)]
        which = f"Cohen's kappa ({kind} weights)" if kind != "none" else "Cohen's kappa"
    else:
        cats = sorted(set(sub.values.ravel().astype(str)))
        n_sub, n_rat = sub.shape
        counts = np.zeros((n_sub, len(cats)))
        for i, (_, row) in enumerate(sub.iterrows()):
            for v in row.astype(str):
                counts[i, cats.index(v)] += 1
        p_j = counts.sum(axis=0) / (n_sub * n_rat)
        P_i = ((counts**2).sum(axis=1) - n_rat) / (n_rat * (n_rat - 1))
        pbar = P_i.mean()
        pe = (p_j**2).sum()
        val = float((pbar - pe) / (1 - pe)) if pe != 1 else np.nan
        ci = [None, None]
        which = "Fleiss' kappa"
    band = ("poor" if val < 0.2 else "fair" if val < 0.4 else "moderate" if val < 0.6
            else "substantial" if val < 0.8 else "almost perfect")
    return {"kind": "kappa", "test": which, "value": val, "ci": ci,
            "n": int(len(sub)), "raters": cols,
            "interpretation": f"{band} agreement (Landis and Koch bands)"}


def cronbach(df, roles, params, ctl=None):
    items = roles.get("items", [])
    sub = df[items].apply(pd.to_numeric, errors="coerce").dropna()
    k = len(items)
    var_sum = sub.var(axis=0, ddof=1).sum()
    var_tot = sub.sum(axis=1).var(ddof=1)
    alpha = float(k / (k - 1) * (1 - var_sum / var_tot)) if var_tot else np.nan
    n = len(sub)
    level = float(params.get("ci", get("ci_level", 0.95)))
    f1 = stats.f.ppf(1 - (1 - level) / 2, n - 1, (n - 1) * (k - 1))
    f2 = stats.f.ppf((1 - level) / 2, n - 1, (n - 1) * (k - 1))
    ci = [float(1 - (1 - alpha) * f1), float(1 - (1 - alpha) * f2)]
    rows = []
    if params.get("drop_stats", True):
        for it in items:
            rest = [i for i in items if i != it]
            if len(rest) < 2:
                continue
            vs = sub[rest].var(axis=0, ddof=1).sum()
            vt = sub[rest].sum(axis=1).var(ddof=1)
            a2 = len(rest) / (len(rest) - 1) * (1 - vs / vt) if vt else np.nan
            rows.append({"item": it, "alpha_if_dropped": float(a2),
                         "item_total_r": float(sub[it].corr(sub[rest].sum(axis=1)))})
    return {"kind": "reliability", "alpha": alpha, "ci": ci, "n": int(n),
            "k_items": k, "items": rows,
            "interpretation": ("questionable" if alpha < 0.7 else
                               "acceptable" if alpha < 0.8 else
                               "good" if alpha < 0.9 else
                               "high, and possibly redundant items")}

RUNNERS = {
    "describe": describe, "freq": freq,
    "crosstab": crosstab, "normality_check": normality_check,
    "variance_check": variance_check, "outlier_check": outlier_check,
    "missing_check": missing_check, "power_achieved": power_achieved,
    "ttest_ind": ttest_ind, "ttest_paired": ttest_paired,
    "ttest_1samp": ttest_1samp, "mannwhitney": mannwhitney,
    "wilcoxon": wilcoxon, "wilcoxon_1samp": wilcoxon_1samp,
    "brunner_munzel": brunner_munzel, "permutation_two": permutation_two,
    "bootstrap_diff": bootstrap_diff, "anova_oneway": anova_oneway,
    "anova_factorial": anova_factorial, "welch_anova": welch_anova,
    "kruskal": kruskal, "friedman": friedman,
    "pairwise": pairwise, "padjust": padjust,
    "multiplicity_audit": multiplicity_audit, "chi2": chi2,
    "fisher": fisher, "mcnemar": mcnemar,
    "cochran_q": cochran_q, "armitage": armitage,
    "prop_test": prop_test, "binomial": binomial,
    "goodness_fit": goodness_fit, "correlation": correlation,
    "icc": icc, "bland_altman": bland_altman,
    "kappa": kappa, "cronbach": cronbach,
}
