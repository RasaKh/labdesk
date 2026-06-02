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

RUNNERS = {
    "linreg": linreg, "logreg": logreg,
}
