"""Regression, diagnostic accuracy and survival."""

import math

import numpy as np
import pandas as pd
from scipy import stats

from ..config import get, have
from ..stats_run import fmt_p
from ..stats_run import fmt_p


def _one(roles, key):
    v = roles.get(key) or []
    return v[0] if v else None


def _design(df, dv, predictors):
    """Complete-case numeric design matrix with missingness preserved.

    In particular, missing categorical values must not become a literal
    ``"nan"`` dummy level and therefore masquerade as observed data.
    """
    y, X, names, keep = _design_frame(df, dv, predictors)
    return y.loc[keep].to_numpy(dtype=float), X.loc[keep].to_numpy(dtype=float), names, int(keep.sum())


def _design_frame(df, dv, predictors):
    """As _design, but returns the full-length outcome, design frame and
    complete-case mask, for callers that must align further columns."""
    y = pd.to_numeric(df[dv], errors="coerce")
    parts, names = [], []
    for c in predictors:
        s = df[c]
        numeric = pd.to_numeric(s, errors="coerce")
        # Treat genuinely numeric/high-cardinality predictors as continuous;
        # otherwise dummy-code the observed categories while leaving missing
        # rows missing across every generated column.
        if pd.api.types.is_numeric_dtype(s) and s.dropna().nunique() > 2:
            parts.append(numeric.rename(c))
            names.append(c)
        else:
            d = pd.get_dummies(s, prefix=c, drop_first=True, dtype=float, dummy_na=False)
            if d.shape[1] == 0:
                # A constant categorical predictor carries no information.
                continue
            d.loc[s.isna(), :] = np.nan
            for col in d.columns:
                parts.append(d[col])
                names.append(str(col))
    if not parts:
        X = pd.DataFrame(index=df.index)
    else:
        X = pd.concat(parts, axis=1)
    keep = y.notna() if X.empty else (X.notna().all(axis=1) & y.notna())
    return y, X, names, keep

def linreg(df, roles, params, ctl=None):
    dv = _one(roles, "dv")
    preds = roles.get("predictors", [])
    y, X, names, n = _design(df, dv, preds)
    if params.get("standardise"):
        X = (X - X.mean(0)) / X.std(0, ddof=1)
        y = (y - y.mean()) / y.std(ddof=1)
    Xc = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(Xc, y, rcond=None)
    fitted = Xc @ beta
    resid = y - fitted
    k = Xc.shape[1]
    dof = n - k
    sigma2 = float(resid @ resid / dof)
    XtX_inv = np.linalg.pinv(Xc.T @ Xc)
    if params.get("robust_se", "none") != "none":
        h = np.einsum("ij,jk,ik->i", Xc, XtX_inv, Xc)
        w = resid**2
        if params["robust_se"] == "HC1":
            w = w * n / dof
        elif params["robust_se"] == "HC3":
            w = w / (1 - h) ** 2
        meat = Xc.T @ (Xc * w[:, None])
        cov = XtX_inv @ meat @ XtX_inv
        se_label = params["robust_se"]
    else:
        cov = sigma2 * XtX_inv
        se_label = "classical"
    se = np.sqrt(np.diag(cov))
    tvals = beta / se
    pvals = 2 * stats.t.sf(np.abs(tvals), dof)
    level = float(params.get("ci", get("ci_level", 0.95)))
    tcrit = stats.t.ppf(1 - (1 - level) / 2, dof)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    ss_res = float(resid @ resid)
    r2 = 1 - ss_res / ss_tot if ss_tot else np.nan
    adj = 1 - (1 - r2) * (n - 1) / dof if dof else np.nan
    F = (ss_tot - ss_res) / (k - 1) / (ss_res / dof) if dof and k > 1 else np.nan
    terms = ["(Intercept)"] + names
    return {
        "kind": "regression", "test": "Linear regression (OLS)", "dv": dv,
        "n": n, "se_type": se_label,
        "coefficients": [
            {"term": t, "estimate": float(b), "se": float(s), "statistic": float(tv),
             "p": float(p), "ci": [float(b - tcrit * s), float(b + tcrit * s)]}
            for t, b, s, tv, p in zip(terms, beta, se, tvals, pvals)],
        "r_squared": float(r2), "adj_r_squared": float(adj),
        "f_statistic": None if np.isnan(F) else float(F),
        "f_p": None if np.isnan(F) else float(stats.f.sf(F, k - 1, dof)),
        "df": [k - 1, dof], "sigma": math.sqrt(sigma2),
        "aic": float(n * math.log(ss_res / n) + 2 * k),
        "bic": float(n * math.log(ss_res / n) + k * math.log(n)),
        "fitted": fitted.tolist()[:5000], "residuals": resid.tolist()[:5000],
        "sentence": (f"R² = {r2:.3f}, adjusted R² = {adj:.3f}"
                     + (f", F({k-1}, {dof}) = {F:.2f}" if not np.isnan(F) else "")),
    }


def logreg(df, roles, params, ctl=None):
    dv = _one(roles, "dv")
    preds = roles.get("predictors", [])
    yraw = df[dv]
    levels = sorted(yraw.dropna().astype(str).unique())
    if len(levels) != 2:
        raise ValueError(f"{dv} has {len(levels)} levels; logistic regression needs 2.")
    ref = str(params.get("ref_level") or levels[0])
    if ref not in levels:
        raise ValueError(f"Reference level {ref!r} is not present in {dv}.")
    pos = [l for l in levels if l != ref][0]
    # Keep missing outcomes missing until the complete-case mask is formed.
    ybin = pd.Series(np.nan, index=df.index, dtype=float)
    valid = yraw.notna()
    ybin.loc[valid] = (yraw.loc[valid].astype(str) == pos).astype(float)
    tmp = df.copy()
    tmp["__y__"] = ybin
    y, X, names, n = _design(tmp, "__y__", preds)
    if n == 0:
        raise ValueError("No complete observations remain after outcome/predictor cleaning.")

    if have("statsmodels"):
        import statsmodels.api as sm
        Xc = sm.add_constant(X, has_constant="add")
        model = sm.Logit(y, Xc).fit(disp=False)
        beta = np.asarray(model.params)
        se = np.asarray(model.bse)
        pvals = np.asarray(model.pvalues)
        llf, llnull = float(model.llf), float(model.llnull)
    else:
        from sklearn.linear_model import LogisticRegression
        lr = LogisticRegression(penalty=None, max_iter=2000)
        lr.fit(X, y)
        beta = np.concatenate([lr.intercept_, lr.coef_.ravel()])
        Xc = np.column_stack([np.ones(len(X)), X])
        p_hat = 1 / (1 + np.exp(-Xc @ beta))
        W = p_hat * (1 - p_hat)
        cov = np.linalg.pinv(Xc.T @ (Xc * W[:, None]))
        se = np.sqrt(np.diag(cov))
        zvals = beta / se
        pvals = 2 * stats.norm.sf(np.abs(zvals))
        eps = 1e-12
        llf = float(np.sum(y * np.log(p_hat + eps) + (1 - y) * np.log(1 - p_hat + eps)))
        pbar = y.mean()
        llnull = float(np.sum(y * math.log(pbar + eps) + (1 - y) * math.log(1 - pbar + eps)))

    level = float(params.get("ci", get("ci_level", 0.95)))
    zcrit = stats.norm.ppf(1 - (1 - level) / 2)
    terms = ["(Intercept)"] + names
    as_or = params.get("report", "or") == "or"
    coefs = []
    for t, b, se_i, pval in zip(terms, beta, se, pvals):
        if as_or:
            with np.errstate(over="ignore", under="ignore"):
                estimate = float(np.exp(b))
                ci_vals = [float(np.exp(b - zcrit * se_i)), float(np.exp(b + zcrit * se_i))]
        else:
            estimate = float(b)
            ci_vals = [float(b - zcrit * se_i), float(b + zcrit * se_i)]
        row = {"term": t, "estimate": estimate, "se": float(se_i),
               "p": float(pval), "ci": ci_vals}
        coefs.append(row)
    Xc = np.column_stack([np.ones(len(X)), X])
    p_hat = 1 / (1 + np.exp(-Xc @ np.asarray(beta)))
    out = {"kind": "regression", "test": "Logistic regression", "dv": dv,
           "positive_class": pos, "reference_class": ref, "n": n,
           "n_events": int(y.sum()),
           "measure": "Odds ratio" if as_or else "log-odds", "ratio_scale": as_or,
           "coefficients": coefs,
           "pseudo_r2_mcfadden": float(1 - llf / llnull) if llnull else None,
           "aic": float(-2 * llf + 2 * len(beta)),
           "predicted": p_hat.tolist()[:5000],
           "observed": y.tolist()[:5000]}
    try:
        from sklearn.metrics import roc_auc_score
        out["auc"] = float(roc_auc_score(y, p_hat))
    except Exception:
        pass
    epv = min(int(y.sum()), int(len(y) - y.sum())) / max(1, len(names))
    if epv < 10:
        out["warning"] = (f"{min(int(y.sum()), int(len(y)-y.sum()))} observations in the rarer outcome "
                          f"class for {len(names)} terms (EPV ≈ {epv:.1f}). Coefficients may be unstable.")
    out["sentence"] = f"n = {n}, {int(y.sum())} events" + (
        f", AUC = {out['auc']:.3f}" if "auc" in out else "")
    return out

# ─── Diagnostic accuracy

# ─── Diagnostic accuracy ─────────────────────────────────────────────────

def _delong_var(y, score):
    """Variance of AUC by the DeLong placement-value method."""
    pos = score[y == 1]
    neg = score[y == 0]
    m, n = len(pos), len(neg)
    if m == 0 or n == 0:
        return np.nan, np.nan
    from scipy.stats import rankdata
    allv = np.concatenate([pos, neg])
    r = rankdata(allv)
    auc = (r[:m].sum() - m * (m + 1) / 2) / (m * n)
    v10 = np.array([(np.sum(p > neg) + 0.5 * np.sum(p == neg)) / n for p in pos])
    v01 = np.array([(np.sum(pos > q) + 0.5 * np.sum(pos == q)) / m for q in neg])
    if m < 2 or n < 2:
        return float(auc), np.nan
    var = v10.var(ddof=1) / m + v01.var(ddof=1) / n
    return float(auc), float(var)


def _binary_positive(series, requested=None, label="binary variable"):
    """Resolve a positive level without relying on lexicographic ordering."""
    vals = [str(v) for v in series.dropna().unique()]
    if len(vals) != 2:
        raise ValueError(f"{label} must contain exactly two observed levels.")
    if requested not in (None, ""):
        req = str(requested)
        if req not in vals:
            raise ValueError(f"Positive level {req!r} is not present in {label}.")
        return req, vals
    # Conventional numeric binary encodings are unambiguous even when CSV import
    # represents them as floats (e.g. 0.0/1.0).  Handle them numerically before
    # falling back to textual conventions.
    try:
        nums = {v: float(v) for v in vals}
        numeric_values = set(nums.values())
        if numeric_values == {0.0, 1.0}:
            return next(v for v, n in nums.items() if n == 1.0), vals
    except (TypeError, ValueError):
        pass

    pos_words = {"1", "true", "yes", "y", "positive", "pos", "present", "case", "event", "disease", "diseased"}
    neg_words = {"0", "false", "no", "n", "negative", "neg", "absent", "control", "none", "censored"}
    low = {v: v.strip().lower() for v in vals}
    hits = [v for v in vals if low[v] in pos_words]
    if len(hits) == 1:
        return hits[0], vals
    neg = [v for v in vals if low[v] in neg_words]
    if len(neg) == 1:
        return [v for v in vals if v != neg[0]][0], vals
    raise ValueError(
        f"Cannot infer which level of {label} is positive from {vals}. "
        "Specify the positive level explicitly rather than relying on label sorting."
    )

def roc(df, roles, params, ctl=None):
    score_c, truth_c = _one(roles, "score"), _one(roles, "truth")
    sub = df[[score_c, truth_c]].copy()
    sub["__score__"] = pd.to_numeric(sub[score_c], errors="coerce")
    sub = sub.dropna(subset=["__score__", truth_c])
    pos, tvals = _binary_positive(sub[truth_c], params.get("positive_level"), truth_c)
    score = sub["__score__"].to_numpy(dtype=float)
    y = (sub[truth_c].astype(str) == pos).astype(int).to_numpy()
    if params.get("direction") == "negative":
        score = -score
    auc, var = _delong_var(y, score)
    level = float(params.get("ci", get("ci_level", 0.95)))
    z = stats.norm.ppf(1 - (1 - level) / 2)
    se = math.sqrt(var) if var == var else np.nan
    thresholds = np.unique(score)
    rows = []
    P, N = int(y.sum()), int(len(y) - y.sum())
    if P == 0 or N == 0:
        raise ValueError("ROC analysis needs at least one positive and one negative observation.")
    prev_raw = params.get("prevalence")
    prev = float(prev_raw) if prev_raw not in (None, "") else P / len(y)
    if not (0 < prev < 1):
        raise ValueError("Prevalence must be strictly between 0 and 1.")
    for t in thresholds:
        pred = score >= t
        tp = int(np.sum(pred & (y == 1)))
        fp = int(np.sum(pred & (y == 0)))
        fn = P - tp
        tn = N - fp
        sn = tp / P
        sp = tn / N
        lr_p = sn / (1 - sp) if sp < 1 else np.inf
        lr_n = (1 - sn) / sp if sp else np.inf
        ppv = (prev * lr_p) / (prev * lr_p + (1 - prev)) if np.isfinite(lr_p) else 1.0
        # Bayes form for NPV using LR-; the previous implementation named the
        # posterior disease probability and then inverted it, which obscured
        # the calculation.
        post_odds_neg = (prev / (1 - prev)) * lr_n
        npv = 1 / (1 + post_odds_neg) if np.isfinite(post_odds_neg) else 0.0
        rows.append({"threshold": float(t), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                     "sensitivity": float(sn), "specificity": float(sp),
                     "youden": float(sn + sp - 1), "ppv": float(ppv), "npv": float(npv),
                     "lr_pos": float(lr_p), "lr_neg": float(lr_n),
                     "accuracy": float((tp + tn) / len(y))})
    rule = params.get("cutpoint", "youden")
    best = None
    if rule == "youden":
        best = max(rows, key=lambda r: r["youden"])
    elif rule == "closest_topleft":
        best = min(rows, key=lambda r: (1 - r["sensitivity"]) ** 2 + (1 - r["specificity"]) ** 2)
    elif rule == "sens_min":
        c = float(params.get("constraint", 0.9))
        cands = [r for r in rows if r["sensitivity"] >= c]
        best = max(cands, key=lambda r: r["specificity"]) if cands else None
    elif rule == "spec_min":
        c = float(params.get("constraint", 0.9))
        cands = [r for r in rows if r["specificity"] >= c]
        best = max(cands, key=lambda r: r["sensitivity"]) if cands else None
    curve = sorted(({"fpr": 1 - r["specificity"], "tpr": r["sensitivity"]} for r in rows),
                   key=lambda d: (d["fpr"], d["tpr"]))
    auc_ci = ([float(max(0, auc - z * se)), float(min(1, auc + z * se))]
              if se == se else None)
    return {"kind": "roc", "test": "ROC analysis", "score": score_c, "truth": truth_c,
            "positive_class": pos, "n": int(len(y)),
            "n_positive": P, "n_negative": N, "auc": auc, "auc_ci": auc_ci,
            "auc_se": se, "prevalence_used": prev,
            "curve": curve[:4000], "operating_points": rows[:2000],
            "best": best, "cutpoint_rule": rule,
            "sentence": (f"AUC = {auc:.3f} " +
                         (f"({int(level*100)}% CI {auc_ci[0]:.3f} to {auc_ci[1]:.3f})"
                          if auc_ci else "")),
            "caveat": ("Predictive values depend on prevalence. The values here use "
                       f"{prev:.3f}; change it in the parameters if the sample is not "
                       "representative of the target population.")}

def diag_2x2(df, roles, params, ctl=None):
    t_col, r_col = _one(roles, "test"), _one(roles, "truth")
    sub = df[[t_col, r_col]].dropna()
    tpos, tl = _binary_positive(sub[t_col], params.get("test_positive_level"), t_col)
    rpos, rl = _binary_positive(sub[r_col], params.get("truth_positive_level"), r_col)
    pred = (sub[t_col].astype(str) == tpos).to_numpy()
    truth = (sub[r_col].astype(str) == rpos).to_numpy()
    tp = int(np.sum(pred & truth)); fp = int(np.sum(pred & ~truth))
    fn = int(np.sum(~pred & truth)); tn = int(np.sum(~pred & ~truth))
    from .basic import _prop_ci
    level = float(params.get("ci", get("ci_level", 0.95)))
    m = params.get("ci_method", "wilson")
    sn, sp = tp / max(1, tp + fn), tn / max(1, tn + fp)
    ppv, npv = tp / max(1, tp + fp), tn / max(1, tn + fn)
    return {"kind": "diagnostic", "test": "Diagnostic accuracy",
            "table": [[tp, fp], [fn, tn]],
            "labels": {"test_positive": tpos, "truth_positive": rpos},
            "n": int(len(sub)),
            "metrics": [
                {"name": "Sensitivity", "value": sn, "ci": list(_prop_ci(tp, tp + fn, m, level))},
                {"name": "Specificity", "value": sp, "ci": list(_prop_ci(tn, tn + fp, m, level))},
                {"name": "Positive predictive value", "value": ppv,
                 "ci": list(_prop_ci(tp, tp + fp, m, level))},
                {"name": "Negative predictive value", "value": npv,
                 "ci": list(_prop_ci(tn, tn + fn, m, level))},
                {"name": "Accuracy", "value": (tp + tn) / len(sub),
                 "ci": list(_prop_ci(tp + tn, len(sub), m, level))},
                {"name": "Positive likelihood ratio",
                 "value": sn / (1 - sp) if sp < 1 else float("inf"), "ci": None},
                {"name": "Negative likelihood ratio",
                 "value": (1 - sn) / sp if sp else float("inf"), "ci": None},
                {"name": "Youden J", "value": sn + sp - 1, "ci": None},
            ],
            "prevalence": float(np.mean(truth)),
            "caveat": "Predictive values apply only at the prevalence in this sample."}

# ─── Survival

# ─── Survival ────────────────────────────────────────────────────────────

def kaplan_meier(df, roles, params, ctl=None):
    t_col, e_col = _one(roles, "time"), _one(roles, "event")
    g_col = _one(roles, "group")
    cols = [t_col, e_col] + ([g_col] if g_col else [])
    sub = df[cols].dropna()
    sub[t_col] = pd.to_numeric(sub[t_col], errors="coerce")
    sub = sub.dropna(subset=[t_col])
    event_level, _ = _binary_positive(sub[e_col], params.get("event_level"), e_col)
    ev = (sub[e_col].astype(str) == event_level).astype(int).to_numpy()

    def km(time, event):
        order = np.argsort(time)
        time, event = np.asarray(time)[order], np.asarray(event)[order]
        n = len(time)
        at_risk = n
        S = 1.0
        var = 0.0
        pts = [{"t": 0.0, "s": 1.0, "at_risk": n, "lo": 1.0, "hi": 1.0, "events": 0}]
        for t in np.unique(time):
            d = int(np.sum((time == t) & (event == 1)))
            c = int(np.sum((time == t) & (event == 0)))
            if d:
                S *= (1 - d / at_risk)
                var += d / (at_risk * (at_risk - d)) if at_risk > d else 0
                se = S * math.sqrt(var) if var >= 0 else 0
                z = 1.959963985
                pts.append({"t": float(t), "s": float(S), "at_risk": int(at_risk),
                            "events": d,
                            "lo": float(max(0, S - z * se)), "hi": float(min(1, S + z * se))})
            at_risk -= (d + c)
            if at_risk <= 0:
                break
        median = next((p["t"] for p in pts if p["s"] <= 0.5), None)
        return pts, median

    def logrank(groups):
        """Two or more group log-rank by the standard O-E construction."""
        alltimes = np.unique(np.concatenate([g[0][g[1] == 1] for g in groups]))
        k = len(groups)
        O = np.zeros(k); E = np.zeros(k)
        V = np.zeros((k, k))
        for t in alltimes:
            n_j = np.array([np.sum(g[0] >= t) for g in groups], float)
            d_j = np.array([np.sum((g[0] == t) & (g[1] == 1)) for g in groups], float)
            n, d = n_j.sum(), d_j.sum()
            if n <= 1 or d == 0:
                continue
            e_j = n_j * d / n
            O += d_j; E += e_j
            f = d * (n - d) / (n - 1)
            for i in range(k):
                for j in range(k):
                    V[i, j] += f * (n_j[i] * ((i == j) * n - n_j[j]) / n**2)
        idx = list(range(k - 1))
        diff = (O - E)[idx]
        Vs = V[np.ix_(idx, idx)]
        stat = float(diff @ np.linalg.pinv(Vs) @ diff)
        return stat, float(stats.chi2.sf(stat, k - 1)), O.tolist(), E.tolist()

    landmarks = [float(x) for x in str(params.get("landmarks") or "").replace(" ", "").split(",") if x]
    out = {"kind": "survival", "test": "Kaplan-Meier", "time": t_col, "event": e_col,
           "event_level": event_level, "curves": []}
    if g_col:
        groups = []
        for lvl, g in sub.groupby(g_col, dropna=True, observed=True):
            mask = sub[g_col] == lvl
            tt = sub.loc[mask, t_col].values
            ee = ev[mask.values]
            pts, med = km(tt, ee)
            groups.append((tt, ee))
            entry = {"label": str(lvl), "n": int(len(tt)), "events": int(ee.sum()),
                     "median": med, "points": pts}
            if landmarks:
                entry["landmarks"] = [
                    {"t": L, "s": next((p["s"] for p in reversed(pts) if p["t"] <= L), 1.0)}
                    for L in landmarks]
            out["curves"].append(entry)
        if params.get("logrank", True) and len(groups) >= 2:
            stat, p, O, E = logrank(groups)
            out.update(statistic=stat, df=len(groups) - 1, p=p,
                       observed=O, expected=E,
                       sentence=f"Log-rank χ²({len(groups)-1}) = {stat:.2f}, {fmt_p(p)}")
            if len(groups) == 2:
                hr = (O[0] / E[0]) / (O[1] / E[1]) if E[0] and E[1] and O[1] else None
                if hr:
                    se = math.sqrt(1 / E[0] + 1 / E[1])
                    out["effects"] = {"hazard_ratio": float(hr),
                                      "hr_ci": [float(math.exp(math.log(hr) - 1.96 * se)),
                                                float(math.exp(math.log(hr) + 1.96 * se))],
                                      "note": "Log-rank derived hazard ratio. "
                                              "Fit a Cox model for adjusted estimates."}
    else:
        pts, med = km(sub[t_col].values, ev)
        out["curves"].append({"label": "All", "n": int(len(sub)),
                              "events": int(ev.sum()), "median": med, "points": pts})
    out["at_risk_table"] = params.get("at_risk", True)
    return out


def cox(df, roles, params, ctl=None):
    from lifelines import CoxPHFitter
    t_col, e_col = _one(roles, "time"), _one(roles, "event")
    preds = roles.get("predictors", [])
    strata = roles.get("strata") or []
    _, X, names, keep = _design_frame(df, t_col, preds)
    time_ = pd.to_numeric(df[t_col], errors="coerce")
    keep &= df[e_col].notna()
    for s_col in strata:
        keep &= df[s_col].notna()
    if not names:
        raise ValueError("No usable covariates: every predictor is constant.")
    if (time_.loc[keep] < 0).any():
        raise ValueError(f"{t_col} has negative times.")
    event_level, _ = _binary_positive(df.loc[keep, e_col], params.get("event_level"), e_col)
    frame = X.loc[keep].copy()
    frame.columns = names
    frame["__time__"] = time_.loc[keep]
    frame["__event__"] = (df.loc[keep, e_col].astype(str) == event_level).astype(int)
    for s_col in strata:
        frame[f"__stratum_{s_col}"] = df.loc[keep, s_col].astype(str)
    n, n_events = len(frame), int(frame["__event__"].sum())
    if n_events == 0:
        raise ValueError(f"No events: no row of {e_col} equals {event_level!r}.")

    level = float(params.get("ci", get("ci_level", 0.95)))
    cph = CoxPHFitter(alpha=1 - level)
    cph.fit(frame, duration_col="__time__", event_col="__event__",
            strata=[f"__stratum_{s}" for s in strata] or None)
    summ = cph.summary
    ci_log = cph.confidence_intervals_
    coefs = [{"term": t, "estimate": float(math.exp(summ.loc[t, "coef"])),
              "log_hr": float(summ.loc[t, "coef"]), "se": float(summ.loc[t, "se(coef)"]),
              "statistic": float(summ.loc[t, "z"]), "p": float(summ.loc[t, "p"]),
              "ci": [float(math.exp(ci_log.loc[t].iloc[0])), float(math.exp(ci_log.loc[t].iloc[1]))]}
             for t in names]
    lr = cph.log_likelihood_ratio_test()
    out = {"kind": "cox", "test": "Cox proportional hazards", "time": t_col, "event": e_col,
           "event_level": event_level, "strata": strata, "n": n, "n_events": n_events,
           "measure": "Hazard ratio", "ratio_scale": True, "ties": "efron",
           "coefficients": coefs,
           "statistic": float(lr.test_statistic), "df": int(lr.degrees_freedom),
           "p": float(lr.p_value), "statistic_label": "Likelihood-ratio χ²",
           "effects": {"concordance": float(cph.concordance_index_)},
           "log_likelihood": float(cph.log_likelihood_),
           "aic": float(cph.AIC_partial_)}
    warnings = []
    epv = n_events / len(names)
    if epv < 10:
        warnings.append(f"{n_events} events for {len(names)} terms (EPV ≈ {epv:.1f}). "
                        "Hazard ratios may be unstable.")
    if params.get("check_ph", True):
        from lifelines.statistics import proportional_hazard_test
        ph = proportional_hazard_test(cph, frame, time_transform="rank").summary
        out["ph_test"] = [{"term": str(t), "statistic": float(r["test_statistic"]),
                           "p": float(r["p"])} for t, r in ph.iterrows()]
        out["ph_method"] = "Scaled Schoenfeld residuals against rank of time"
        bad = [r["term"] for r in out["ph_test"] if r["p"] < get("alpha", 0.05)]
        if bad:
            warnings.append("Proportional hazards may not hold for " + ", ".join(bad)
                            + ". Consider stratifying by it or adding a time interaction.")
    if warnings:
        out["warning"] = " ".join(warnings)
    out["sentence"] = (f"n = {n}, {n_events} events, likelihood-ratio χ²({out['df']}) = "
                       f"{out['statistic']:.2f}, {fmt_p(out['p'])}, "
                       f"C = {out['effects']['concordance']:.3f}")
    return out


def ancova(df, roles, params, ctl=None):
    import statsmodels.formula.api as smf
    from statsmodels.stats.anova import anova_lm
    dv, group = _one(roles, "dv"), _one(roles, "group")
    covs = roles.get("covariates") or []
    if not covs:
        raise ValueError("ANCOVA needs at least one covariate.")
    # Fixed internal names keep arbitrary column labels out of the formula.
    d = pd.DataFrame({"y": pd.to_numeric(df[dv], errors="coerce"), "g": df[group]})
    cnames = [f"c{i}" for i in range(len(covs))]
    for cn, c in zip(cnames, covs):
        d[cn] = pd.to_numeric(df[c], errors="coerce")
    d = d.dropna()
    d["g"] = d["g"].astype(str)
    levels = [str(lvl) for lvl, _ in df.loc[d.index].groupby(group, observed=True)]
    if len(levels) < 2:
        raise ValueError(f"{group} has fewer than two levels with complete data.")
    rhs = " + ".join(cnames)
    model = smf.ols(f"y ~ C(g) + {rhs}", data=d).fit()
    table = anova_lm(model, typ=2)
    label = {"C(g)": group, "Residual": "Residual", **dict(zip(cnames, covs))}
    ss_res = float(table.loc["Residual", "sum_sq"])
    df_res = int(table.loc["Residual", "df"])
    g_row = table.loc["C(g)"]
    F, p_val, df_g = float(g_row["F"]), float(g_row["PR(>F)"]), int(g_row["df"])
    rows = []
    for key, r in table.iterrows():
        row = {"source": label[key], "ss": float(r["sum_sq"]), "df": int(r["df"]),
               "ms": float(r["sum_sq"] / r["df"])}
        if key != "Residual":
            row.update(F=float(r["F"]), p=float(r["PR(>F)"]),
                       partial_eta_squared=float(r["sum_sq"] / (r["sum_sq"] + ss_res)))
        rows.append(row)

    grouped = d.groupby("g")["y"]
    out = {"kind": "anova", "test": "ANCOVA", "dv": dv, "factor": group, "covariates": covs,
           "levels": levels, "n": [int(grouped.size()[l]) for l in levels],
           "mean": [float(grouped.mean()[l]) for l in levels],
           "sd": [float(grouped.std(ddof=1)[l]) for l in levels],
           "sem": [float(grouped.std(ddof=1)[l] / math.sqrt(grouped.size()[l])) for l in levels],
           "means_note": "Group means and SDs are observed (unadjusted); "
                         "see adjusted means for the covariate-adjusted comparison.",
           "statistic": F, "df": [df_g, df_res], "p": p_val, "table": rows,
           "effects": {"partial_eta_squared": float(g_row["sum_sq"] / (g_row["sum_sq"] + ss_res))},
           "r_squared": float(model.rsquared)}

    level = float(params.get("ci", get("ci_level", 0.95)))
    if params.get("emmeans", True):
        grid = pd.DataFrame({"g": levels, **{cn: float(d[cn].mean()) for cn in cnames}})
        pred = model.get_prediction(grid).summary_frame(alpha=1 - level)
        out["adjusted_means"] = [
            {"group": l, "n": n_l, "observed_mean": m, "adjusted_mean": float(r["mean"]),
             "se": float(r["mean_se"]), "ci_low": float(r["mean_ci_lower"]),
             "ci_high": float(r["mean_ci_upper"])}
            for l, n_l, m, (_, r) in zip(levels, out["n"], out["mean"], pred.iterrows())]
        out["adjusted_at"] = {c: float(d[cn].mean()) for c, cn in zip(covs, cnames)}
    if params.get("homog_slopes", True):
        full = smf.ols(f"y ~ C(g) * ({rhs})", data=d).fit()
        cmp = anova_lm(model, full)
        Fs, ps = float(cmp["F"].iloc[1]), float(cmp["Pr(>F)"].iloc[1])
        out["slopes_test"] = {"F": Fs, "df": [int(cmp["df_diff"].iloc[1]), int(cmp["df_resid"].iloc[1])],
                              "p": ps}
        if ps < get("alpha", 0.05):
            out["warning"] = (f"Regression slopes differ between groups (F = {Fs:.2f}, {fmt_p(ps)}). "
                              "The adjusted group difference then depends on the covariate value, "
                              "and a single ANCOVA estimate does not summarise it.")
    out["sentence"] = (f"F({df_g}, {df_res}) = {F:.2f}, {fmt_p(p_val)}, "
                       f"partial η² = {out['effects']['partial_eta_squared']:.3f}")
    return out

RUNNERS = {
    "linreg": linreg, "logreg": logreg,
    "roc": roc, "diag_2x2": diag_2x2,
    "kaplan_meier": kaplan_meier, "cox": cox,
    "ancova": ancova,
}
