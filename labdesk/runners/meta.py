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


def meta_bias(df, roles, params, ctl=None):
    yi = pd.to_numeric(df[_one(roles, "effect")], errors="coerce").values
    se = pd.to_numeric(df[_one(roles, "se")], errors="coerce").values
    ok = ~(np.isnan(yi) | np.isnan(se)) & (se > 0)
    yi, se = yi[ok], se[ok]
    k = len(yi)
    out = {"kind": "meta_bias", "k": k, "tests": [],
           "points": [{"yi": float(a), "se": float(b)} for a, b in zip(yi, se)]}
    want = params.get("tests") or ["egger", "trimfill"]

    if k < 10:
        out["warning"] = (f"{k} studies. Tests for funnel asymmetry are underpowered "
                          "below about ten studies and should not be reported as "
                          "evidence of absence.")

    if "egger" in want and k >= 3:
        prec = 1 / se
        snd = yi / se
        sl, ic, r, p, sd = stats.linregress(prec, snd)
        out["tests"].append({"name": "Egger regression intercept", "estimate": float(ic),
                             "se": float(sd), "p": float(p),
                             "interpretation": ("Funnel asymmetry present."
                                                if p < 0.1 else "No clear asymmetry.")})
    if "begg" in want and k >= 3:
        wf = 1 / se**2
        mu = np.sum(wf * yi) / np.sum(wf)
        v_star = se**2 - 1 / np.sum(wf)
        t_star = (yi - mu) / np.sqrt(np.maximum(v_star, 1e-12))
        tau, p = stats.kendalltau(t_star, se**2)
        out["tests"].append({"name": "Begg rank correlation", "estimate": float(tau),
                             "p": float(p)})
    if "trimfill" in want and k >= 3:
        y = yi.copy(); s = se.copy()
        mu = float(np.sum(y / s**2) / np.sum(1 / s**2))
        k0 = 0
        for _ in range(50):
            centred = y - mu
            order = np.argsort(np.abs(centred))
            ranks = np.empty(len(y)); ranks[order] = np.arange(1, len(y) + 1)
            signed = np.sign(centred) * ranks
            Tn = signed[signed > 0].sum()
            n = len(y)
            new_k0 = int(max(0, round((4 * Tn - n * (n + 1)) / (2 * n - 1))))
            if new_k0 == k0:
                break
            k0 = new_k0
            keep = np.argsort(centred)[:len(y) - k0] if centred.mean() > 0 else \
                np.argsort(centred)[k0:]
            mu = float(np.sum(y[keep] / s[keep] ** 2) / np.sum(1 / s[keep] ** 2))
        side = "left" if np.mean(yi) > mu else "right"
        out["tests"].append({"name": "Trim and fill", "missing_studies": k0,
                             "adjusted_pooled": mu,
                             "interpretation": (f"Estimates {k0} missing studies on the "
                                                f"{side}; adjusted pooled effect {mu:.3f}."
                                                if k0 else "No studies imputed.")})
    return out


def meta_sensitivity(df, roles, params, ctl=None):
    labels, yi, vi = _prepare(df, roles, params)
    ok = ~(np.isnan(yi) | np.isnan(vi)) & (vi > 0)
    labels = [l for l, kk in zip(labels, ok) if kk]
    yi, vi = yi[ok], vi[ok]
    k = len(yi)
    mode = params.get("mode", "loo")
    z = 1.959963985

    def pool(y, v):
        t2 = _tau2(y, v, "REML")
        w = 1 / (v + t2)
        mu = float(np.sum(w * y) / np.sum(w))
        se = float(math.sqrt(1 / np.sum(w)))
        Q = float(np.sum((1 / v) * (y - np.sum(y / v) / np.sum(1 / v)) ** 2))
        I2 = max(0.0, 100 * (Q - (len(y) - 1)) / Q) if Q > 0 else 0.0
        return mu, se, I2

    rows = []
    if mode == "cumulative":
        order = list(range(k))
        sb = params.get("sort_by")
        if sb and sb in df.columns:
            order = list(np.argsort(pd.to_numeric(df[sb], errors="coerce").values[ok]))
        for i in range(1, k + 1):
            idx = order[:i]
            mu, se, I2 = pool(yi[idx], vi[idx])
            rows.append({"label": f"+ {labels[order[i-1]]}", "k": i, "pooled": mu,
                         "ci": [mu - z * se, mu + z * se], "i2": I2})
    else:
        full_mu, _, _ = pool(yi, vi)
        for i in range(k):
            idx = [j for j in range(k) if j != i]
            mu, se, I2 = pool(yi[idx], vi[idx])
            rows.append({"label": f"Omitting {labels[i]}", "k": k - 1, "pooled": mu,
                         "ci": [mu - z * se, mu + z * se], "i2": I2,
                         "shift": mu - full_mu})
        rows.sort(key=lambda r: -abs(r.get("shift", 0)))
    return {"kind": "meta_sensitivity", "mode": mode, "rows": rows, "k": k,
            "note": ("Studies are ordered by how much omitting them moves the pooled "
                     "estimate." if mode == "loo" else
                     "The pooled estimate as each study was added.")}


def evalue(df, roles, params, ctl=None):
    est = float(params.get("estimate") or 0)
    measure = params.get("measure", "RR")
    if measure == "OR":
        rr = math.sqrt(est) if params.get("rare") else est
        note = ("Odds ratio approximated to a risk ratio by its square root, which "
                "assumes the outcome is not rare." if not params.get("rare")
                else "Rare outcome, so the odds ratio was used directly as a risk ratio.")
    elif measure == "HR":
        rr = (1 - 0.5 ** math.sqrt(est)) / (1 - 0.5 ** math.sqrt(1 / est)) if est > 0 else np.nan
        note = "Hazard ratio converted by the VanderWeele approximation."
    elif measure == "SMD":
        rr = math.exp(0.91 * est)
        note = "Standardised mean difference converted by exp(0.91 × d)."
    else:
        rr = est
        note = "Risk ratio used directly."

    def ev(r):
        if r is None or r != r or r <= 0:
            return None
        if r < 1:
            r = 1 / r
        return float(r + math.sqrt(r * (r - 1)))

    lo = params.get("lo")
    hi = params.get("hi")
    bound = None
    if lo not in (None, "") and hi not in (None, ""):
        lo, hi = float(lo), float(hi)
        if measure == "OR" and not params.get("rare"):
            lo, hi = math.sqrt(lo), math.sqrt(hi)
        if lo > 1:
            bound = ev(lo)
        elif hi < 1:
            bound = ev(hi)
        else:
            bound = 1.0
    return {"kind": "evalue", "estimate": est, "measure": measure,
            "risk_ratio_used": rr, "evalue_point": ev(rr),
            "evalue_ci": bound, "conversion_note": note,
            "interpretation": (
                f"An unmeasured confounder would need to be associated with both the "
                f"exposure and the outcome by a risk ratio of at least "
                f"{ev(rr):.2f} each, above and beyond the measured covariates, to "
                f"explain away the point estimate."
                + (f" To move the confidence limit to the null it would need "
                   f"{bound:.2f}." if bound and bound > 1 else
                   " The interval already includes the null." if bound == 1.0 else "")),
            "cite": "VanderWeele TJ, Ding P. Ann Intern Med. 2017."}


RUNNERS = {
    "meta_effect": meta_effect,
    "meta_bias": meta_bias,
    "meta_sensitivity": meta_sensitivity,
    "evalue": evalue,
}
