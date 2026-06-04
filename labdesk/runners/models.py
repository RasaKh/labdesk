"""Regression, diagnostic accuracy and survival."""

import math

import numpy as np
import pandas as pd
from scipy import stats

from ..config import get, have


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

RUNNERS = {
    "linreg": linreg, "logreg": logreg,
    "roc": roc, "diag_2x2": diag_2x2,
}
