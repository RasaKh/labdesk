"""Meta-analysis, publication bias, sensitivity, and the E-value."""

import math

import numpy as np
import pandas as pd
from scipy import stats

from ..config import get

LOG_MEASURES = {"OR", "RR", "HR"}


def _one(roles, key):
    v = roles.get(key) or []
    return v[0] if v else None


def _tau2(yi, vi, method="REML", max_iter=100):
    """Between-study variance. DL closed form, REML and PM by iteration."""
    k = len(yi)
    wi = 1 / vi
    if method == "DL" or k < 2:
        mu = np.sum(wi * yi) / np.sum(wi)
        Q = np.sum(wi * (yi - mu) ** 2)
        C = np.sum(wi) - np.sum(wi**2) / np.sum(wi)
        return max(0.0, float((Q - (k - 1)) / C)) if C else 0.0
    if method == "SJ":
        mu = yi.mean()
        v_hat = np.sum((yi - mu) ** 2) / (k - 1)
        wi2 = 1 / (vi + v_hat)
        mu2 = np.sum(wi2 * yi) / np.sum(wi2)
        # Sidik-Jonkman weights are 1/(vi/t0 + 1) = t0 * wi2, so the scale
        # factor t0 must multiply the weighted sum of squares.
        return float(v_hat * np.sum(wi2 * (yi - mu2) ** 2) / (k - 1))
    t2 = _tau2(yi, vi, "DL")
    for _ in range(max_iter):
        w = 1 / (vi + t2)
        mu = np.sum(w * yi) / np.sum(w)
        if method == "PM":
            Q = np.sum(w * (yi - mu) ** 2)
            new = t2 + (Q - (k - 1)) / np.sum(w) if np.sum(w) else t2
        else:
            # Viechtbauer (2005) REML fixed point. The 1/Σw term is the
            # degrees-of-freedom correction that separates REML from ML;
            # dropping it is the usual way this comes out too large.
            new = (np.sum(w**2 * ((yi - mu) ** 2 - vi)) / np.sum(w**2)
                   + 1 / np.sum(w))
        new = max(0.0, float(new))
        if abs(new - t2) < 1e-10:
            t2 = new
            break
        t2 = new
    return float(t2)


def _prepare(df, roles, params):
    """Turn whatever the user supplied into (labels, yi, vi)."""
    measure = params.get("measure", "SMD")
    kind = params.get("input", "generic")
    study_c = _one(roles, "study")
    labels = df[study_c].astype(str).tolist() if study_c else \
        [f"Study {i+1}" for i in range(len(df))]
    if kind == "generic":
        yi = pd.to_numeric(df[_one(roles, "effect")], errors="coerce").values
        se = pd.to_numeric(df[_one(roles, "se")], errors="coerce").values
        if measure in LOG_MEASURES and np.nanmin(yi) > 0:
            yi = np.log(yi)
        return labels, yi.astype(float), (se**2).astype(float)
    raise ValueError(
        "Meta-analysis accepts study-level effect estimates and standard errors."
    )


def meta_effect(df, roles, params, ctl=None):
    labels, yi, vi = _prepare(df, roles, params)
    ok = ~(np.isnan(yi) | np.isnan(vi)) & (vi > 0)
    labels = [l for l, k in zip(labels, ok) if k]
    yi, vi = yi[ok], vi[ok]
    k = len(yi)
    if k < 2:
        raise ValueError("Need at least two studies with a usable effect and standard error.")
    measure = params.get("measure", "SMD")
    level = float(params.get("ci", get("ci_level", 0.95)))
    z = stats.norm.ppf(1 - (1 - level) / 2)

    wf = 1 / vi
    mu_f = float(np.sum(wf * yi) / np.sum(wf))
    se_f = float(math.sqrt(1 / np.sum(wf)))
    Q = float(np.sum(wf * (yi - mu_f) ** 2))
    p_Q = float(stats.chi2.sf(Q, k - 1))
    I2 = max(0.0, 100 * (Q - (k - 1)) / Q) if Q > 0 else 0.0
    H = math.sqrt(Q / (k - 1)) if k > 1 else 1.0

    random = params.get("model", "random") == "random"
    tau2 = _tau2(yi, vi, params.get("tau_method", "REML")) if random else 0.0
    w = 1 / (vi + tau2)
    mu = float(np.sum(w * yi) / np.sum(w))
    se = float(math.sqrt(1 / np.sum(w)))

    if random and params.get("knha", True) and k > 2:
        s2 = np.sum(w * (yi - mu) ** 2) / (k - 1)
        se = float(math.sqrt(max(s2, 1e-12) / np.sum(w)))
        crit = stats.t.ppf(1 - (1 - level) / 2, k - 1)
        p = float(2 * stats.t.sf(abs(mu / se), k - 1))
        method_note = "Hartung-Knapp adjusted"
    else:
        crit = z
        p = float(2 * stats.norm.sf(abs(mu / se)))
        method_note = "Wald"

    lo, hi = mu - crit * se, mu + crit * se
    pi = None
    if random and params.get("prediction", True) and k > 2:
        pse = math.sqrt(tau2 + se**2)
        t = stats.t.ppf(1 - (1 - level) / 2, k - 2)
        pi = [mu - t * pse, mu + t * pse]

    exp_ = measure in LOG_MEASURES

    def out_val(v):
        return float(math.exp(v)) if exp_ else float(v)

    total_w = np.sum(w)
    studies = [{"label": l, "effect": out_val(y), "yi": float(y),
                "se": float(math.sqrt(v)),
                "ci": [out_val(y - z * math.sqrt(v)), out_val(y + z * math.sqrt(v))],
                "weight": float(100 * ww / total_w)}
               for l, y, v, ww in zip(labels, yi, vi, w)]

    res = {"kind": "meta", "test": "Meta-analysis", "measure": measure,
           "model": "Random effects" if random else "Fixed effect",
           "tau_method": params.get("tau_method", "REML") if random else None,
           "inference": method_note,
           "k": k, "studies": studies,
           "pooled": out_val(mu), "pooled_ci": [out_val(lo), out_val(hi)],
           "pooled_raw": mu, "se": se, "p": p,
           "prediction_interval": [out_val(pi[0]), out_val(pi[1])] if pi else None,
           "heterogeneity": {"Q": Q, "df": k - 1, "p": p_Q, "I2": float(I2),
                             "tau2": float(tau2), "tau": float(math.sqrt(tau2)),
                             "H": float(H)},
           "null_line": 1.0 if exp_ else 0.0,
           "log_scale": exp_,
           "sentence": (f"Pooled {measure} = {out_val(mu):.2f} "
                        f"({int(level*100)}% CI {out_val(lo):.2f} to {out_val(hi):.2f}), "
                        f"I² = {I2:.0f}%, τ² = {tau2:.3f}")}

    if I2 > 75:
        res["warning"] = (f"I² = {I2:.0f}%. With heterogeneity this high the pooled "
                          "estimate may not describe any real population. Explore "
                          "subgroups or reconsider pooling.")
    if k < 5 and random:
        res.setdefault("warning", "")
        res["warning"] += (" Fewer than five studies makes τ² poorly estimated; "
                           "the Hartung-Knapp interval is the more honest one.")

    sg = params.get("subgroup")
    if sg and sg in df.columns:
        blocks = []
        for lvl, sub in df[ok].groupby(sg, dropna=True, observed=True):
            m = sub.index
            yy = yi[[list(df[ok].index).index(i) for i in m]]
            vv = vi[[list(df[ok].index).index(i) for i in m]]
            if len(yy) < 2:
                continue
            t2s = _tau2(yy, vv, params.get("tau_method", "REML")) if random else 0
            ws = 1 / (vv + t2s)
            ms = float(np.sum(ws * yy) / np.sum(ws))
            ses = float(math.sqrt(1 / np.sum(ws)))
            blocks.append({"level": str(lvl), "k": len(yy), "pooled": out_val(ms),
                           "ci": [out_val(ms - z * ses), out_val(ms + z * ses)]})
        if len(blocks) >= 2:
            qb = sum((b["k"]) for b in blocks)
            res["subgroups"] = {"by": sg, "blocks": blocks,
                                "note": f"Subgroup comparison across {len(blocks)} levels. "
                                        "Subgroup differences are observational even in "
                                        "a meta-analysis of randomised trials."}
    return res

RUNNERS = {
    "meta_effect": meta_effect,
}
