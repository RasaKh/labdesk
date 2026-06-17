"""Bench assays, dimensionality reduction, and equivalence testing."""

import math

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import curve_fit

from ..config import get, have
from ..stats_run import cohen_d, fmt_p


def _one(roles, key):
    v = roles.get(key) or []
    return v[0] if v else None


# ─── qPCR ────────────────────────────────────────────────────────────────

def qpcr(df, roles, params, ctl=None):
    ct_c = _one(roles, "ct"); gene_c = _one(roles, "gene")
    samp_c = _one(roles, "sample"); grp_c = _one(roles, "group")
    d = df[[ct_c, gene_c, samp_c, grp_c]].copy()
    d[ct_c] = pd.to_numeric(d[ct_c], errors="coerce")
    d = d.dropna()

    refs = [g.strip() for g in str(params.get("reference_genes") or "").split(",") if g.strip()]
    if not refs:
        raise ValueError("Name at least one reference gene.")
    present = {str(x) for x in d[gene_c].unique()}
    missing_refs = [r for r in refs if r not in present]
    if missing_refs:
        raise ValueError("Reference gene(s) not present in the data: " + ", ".join(missing_refs))
    genes = [g for g in d[gene_c].unique() if str(g) not in refs]

    # Replicate quality control before any arithmetic.
    rep = d.groupby([samp_c, gene_c])[ct_c].agg(["mean", "std", "count"]).reset_index()
    max_sd = float(params.get("max_replicate_sd", 0.5))
    flagged = rep[(rep["std"] > max_sd) & (rep["count"] > 1)]
    qc = [{"sample": str(r[samp_c]), "gene": str(r[gene_c]),
           "sd": float(r["std"]), "n": int(r["count"])} for _, r in flagged.iterrows()]

    mean_ct = rep.set_index([samp_c, gene_c])["mean"]
    grp_of = d.groupby(samp_c)[grp_c].first()
    samples = list(grp_of.index)
    calibrator = str(params.get("calibrator") or grp_of.iloc[0])
    if calibrator not in {str(x) for x in grp_of.values}:
        raise ValueError(f"Calibrator group {calibrator!r} is not present in the data.")

    eff = {}
    if params.get("efficiency") == "pfaffl":
        for tok in str(params.get("efficiencies") or "").split(","):
            if "=" in tok:
                k, v = tok.split("=", 1)
                eff[k.strip()] = float(v)
        required = set(refs) | {str(g) for g in genes}
        missing_eff = sorted(g for g in required if g not in eff)
        if missing_eff:
            raise ValueError("Pfaffl correction needs an efficiency for every target/reference gene: " +
                             ", ".join(missing_eff))
        bad = [g for g in required if not (1.0 < eff[g] <= 2.5)]
        if bad:
            raise ValueError("qPCR efficiencies must be plausible amplification factors (>1 and <=2.5): " +
                             ", ".join(sorted(bad)))

    def E(g):
        return float(eff.get(str(g), 2.0))

    # Calibrator means are computed per gene.  This is needed for the Pfaffl
    # ratio and also avoids double-applying the reference-gene correction.
    cal_samples = [s for s in samples if str(grp_of.get(s)) == calibrator]
    cal_gene_mean = {}
    for g in list(genes) + refs:
        vals = [mean_ct.get((s, g)) for s in cal_samples]
        vals = [float(v) for v in vals if v is not None and v == v]
        if vals:
            cal_gene_mean[str(g)] = float(np.mean(vals))

    def _looks_normal(arr):
        arr = np.asarray(arr, float)
        if len(arr) < 3:
            return True  # no evidence to reject normality at this sample size
        if len(arr) > 5000:
            return True
        try:
            return bool(stats.shapiro(arr).pvalue >= 0.05)
        except Exception:
            return True

    rows = []
    for g in genes:
        ref_ct = {}
        for s in samples:
            vals = [mean_ct.get((s, r)) for r in refs]
            vals = [float(v) for v in vals if v is not None and v == v]
            ref_ct[s] = float(np.mean(vals)) if len(vals) == len(refs) else np.nan

        dct = {}
        for s in samples:
            tgt = mean_ct.get((s, g))
            if tgt is None or tgt != tgt or ref_ct.get(s) != ref_ct.get(s):
                continue
            dct[s] = float(tgt - ref_ct[s])
        cal_vals = [v for s, v in dct.items() if str(grp_of.get(s)) == calibrator]
        if not cal_vals:
            continue
        cal_mean = float(np.mean(cal_vals))

        recs = []
        for s, v in dct.items():
            ddct = float(v - cal_mean)
            if params.get("efficiency") == "pfaffl":
                tgt_ct = mean_ct.get((s, g))
                cal_tgt = cal_gene_mean.get(str(g))
                ref_terms = []
                for r in refs:
                    sample_ref = mean_ct.get((s, r))
                    cal_ref = cal_gene_mean.get(str(r))
                    if sample_ref is None or sample_ref != sample_ref or cal_ref is None:
                        ref_terms = []
                        break
                    ref_terms.append(E(r) ** (cal_ref - float(sample_ref)))
                if cal_tgt is None or tgt_ct is None or not ref_terms:
                    continue
                target_ratio = E(g) ** (cal_tgt - float(tgt_ct))
                ref_norm = float(np.prod(ref_terms) ** (1.0 / len(ref_terms)))
                fc = target_ratio / ref_norm if ref_norm > 0 else np.nan
            else:
                fc = 2.0 ** (-ddct)
            if not np.isfinite(fc) or fc <= 0:
                continue
            recs.append({"sample": str(s), "group": str(grp_of.get(s)),
                         "dct": float(v), "ddct": ddct, "fold_change": float(fc),
                         "log2fc": float(np.log2(fc))})

        by_group_fc = {}
        by_group_dct = {}
        for r in recs:
            by_group_fc.setdefault(r["group"], []).append(r["fold_change"])
            by_group_dct.setdefault(r["group"], []).append(r["dct"])
        levels = list(by_group_fc)
        arrays = [np.asarray(by_group_dct[k], float) for k in levels
                  if len(by_group_dct[k]) > 1]

        # Inference is performed on ΔCt, not the exponentiated fold-change
        # scale.  Fold changes remain the reported effect for interpretability.
        p = None; test = None
        which = params.get("test", "auto")
        if len(arrays) == 2:
            if which == "mwu":
                p = float(stats.mannwhitneyu(*arrays, alternative="two-sided").pvalue)
                test = "Mann-Whitney on ΔCt"
            elif which == "kruskal":
                p = float(stats.kruskal(*arrays).pvalue)
                test = "Kruskal-Wallis on ΔCt"
            elif which == "anova":
                p = float(stats.f_oneway(*arrays).pvalue)
                test = "ANOVA on ΔCt"
            elif which == "ttest" or (which == "auto" and all(_looks_normal(a) for a in arrays)):
                p = float(stats.ttest_ind(*arrays, equal_var=False).pvalue)
                test = "Welch t on ΔCt"
            elif which == "auto":
                p = float(stats.mannwhitneyu(*arrays, alternative="two-sided").pvalue)
                test = "Mann-Whitney on ΔCt"
            else:
                raise ValueError(f"Unsupported qPCR group comparison {which!r}.")
        elif len(arrays) > 2:
            if which in ("ttest", "mwu"):
                raise ValueError(f"{which!r} is a two-group comparison; use ANOVA, Kruskal-Wallis, or Automatic for 3+ groups.")
            if which == "kruskal" or (which == "auto" and not all(_looks_normal(a) for a in arrays)):
                p = float(stats.kruskal(*arrays).pvalue)
                test = "Kruskal-Wallis on ΔCt"
            elif which in ("anova", "auto"):
                p = float(stats.f_oneway(*arrays).pvalue)
                test = "ANOVA on ΔCt"
            else:
                raise ValueError(f"Unsupported qPCR group comparison {which!r}.")

        rows.append({"gene": str(g), "calibrator": calibrator,
                     "levels": levels,
                     "mean_fold_change": [float(np.mean(by_group_fc[k])) for k in levels],
                     "sem": [float(np.std(by_group_fc[k], ddof=1) / math.sqrt(len(by_group_fc[k])))
                             if len(by_group_fc[k]) > 1 else 0.0 for k in levels],
                     "n": [len(by_group_fc[k]) for k in levels],
                     "p": p, "test": test, "inference_scale": "delta Ct", "samples": recs})

    out = {"kind": "qpcr", "test": "Relative quantification",
           "method": ("Pfaffl efficiency-corrected" if params.get("efficiency") == "pfaffl"
                      else "2^-ΔΔCt"),
           "reference_genes": refs, "calibrator": calibrator,
           "genes": rows, "qc_flags": qc,
           "levels": rows[0]["levels"] if rows else [],
           "mean": rows[0]["mean_fold_change"] if rows else [],
           "sem": rows[0]["sem"] if rows else [],
           "comparisons": ([{"a": rows[0]["levels"][0], "b": rows[0]["levels"][1],
                             "p": rows[0]["p"]}]
                           if rows and rows[0].get("p") is not None
                           and len(rows[0]["levels"]) == 2 else [])}
    if qc:
        out["warning"] = (f"{len(qc)} sample-gene pairs have replicate SD above {max_sd} Ct. "
                          "Check those wells before trusting the fold changes.")

    if params.get("stability", True) and len(refs) > 1:
        M = {}
        for r in refs:
            devs = []
            for r2 in refs:
                if r == r2:
                    continue
                ratios = []
                for s in samples:
                    a, b = mean_ct.get((s, r)), mean_ct.get((s, r2))
                    if a == a and b == b:
                        ratios.append(a - b)
                if len(ratios) > 1:
                    devs.append(float(np.std(ratios, ddof=1)))
            M[r] = float(np.mean(devs)) if devs else None
        out["reference_stability"] = {"geNorm_M": M,
                                      "note": "Lower M indicates more stable reference-gene expression; interpret cutoffs in the context of the sample type."}
    return out


# ─── ELISA ───────────────────────────────────────────────────────────────

def _fourpl(x, a, b, c, d):
    return d + (a - d) / (1 + (x / c) ** b)


def _fivepl(x, a, b, c, d, g):
    return d + (a - d) / (1 + (x / c) ** b) ** g


def elisa(df, roles, params, ctl=None):
    od_c = _one(roles, "od"); conc_c = _one(roles, "conc")
    type_c = _one(roles, "sample_type"); well_c = _one(roles, "well")
    d = df.copy()
    d[od_c] = pd.to_numeric(d[od_c], errors="coerce")
    if conc_c:
        d[conc_c] = pd.to_numeric(d[conc_c], errors="coerce")

    if type_c:
        # Do not use startswith("s"): common labels such as "sample" would be
        # silently classified as standards.  Accept explicit standard labels.
        typ = d[type_c].astype(str).str.strip().str.lower()
        is_std = typ.isin({"standard", "standards", "std", "calibrator", "cal", "standard curve"})
        std = d[is_std]
        unk = d[~is_std]
        if std.empty and conc_c:
            # Concentration is the authoritative fallback when labels are custom.
            std = d[d[conc_c].notna()]
            unk = d[d[conc_c].isna()]
    elif conc_c:
        std = d[d[conc_c].notna()]
        unk = d[d[conc_c].isna()]
    else:
        raise ValueError("Provide either standard concentrations or a sample-type column.")
    if not conc_c:
        raise ValueError("A standard-concentration column is required to fit an ELISA curve.")

    model = params.get("model", "4pl")
    if model not in {"4pl", "5pl", "linear", "loglinear"}:
        raise ValueError(f"Unsupported ELISA curve model: {model!r}")
    sx = pd.to_numeric(std[conc_c], errors="coerce").to_numpy(float)
    sy = pd.to_numeric(std[od_c], errors="coerce").to_numpy(float)
    ok = np.isfinite(sx) & np.isfinite(sy) & (sx > 0)
    sx, sy = sx[ok], sy[ok]
    min_distinct = {"linear": 2, "loglinear": 2, "4pl": 4, "5pl": 5}[model]
    if len(np.unique(sx)) < min_distinct:
        raise ValueError(f"{model.upper()} needs at least {min_distinct} distinct positive standard concentrations.")

    weight = params.get("weighting", "1/y2")
    # scipy.optimize.curve_fit minimises sum((residual/sigma)^2).  Therefore
    # a desired 1/y weight corresponds to sigma=sqrt(|y|), and 1/y² to sigma=|y|.
    sigma = None
    abs_y = np.maximum(np.abs(sy), 1e-8)
    if weight == "1/y":
        sigma = np.sqrt(abs_y)
    elif weight == "1/y2":
        sigma = abs_y
    elif weight != "none":
        raise ValueError(f"Unsupported ELISA weighting: {weight!r}")

    def linear(x, m, b):
        return m * x + b

    def loglinear(x, m, b):
        return m * np.log10(x) + b

    if model == "linear":
        fn = linear
        m0, b0 = np.polyfit(sx, sy, 1)
        p0 = [float(m0), float(b0)]
    elif model == "loglinear":
        fn = loglinear
        m0, b0 = np.polyfit(np.log10(sx), sy, 1)
        p0 = [float(m0), float(b0)]
    elif model == "5pl":
        fn = _fivepl
        p0 = [float(sy.min()), 1.0, float(np.median(sx)), float(sy.max()), 1.0]
    else:
        fn = _fourpl
        p0 = [float(sy.min()), 1.0, float(np.median(sx)), float(sy.max())]

    popt, pcov = curve_fit(fn, sx, sy, p0=p0, sigma=sigma, maxfev=200000,
                           absolute_sigma=False)
    pred = np.asarray(fn(sx, *popt), float)
    ss_res = float(np.sum((sy - pred) ** 2))
    ss_tot = float(np.sum((sy - sy.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot else np.nan

    def back(y):
        try:
            if model == "linear":
                m, b = popt
                if abs(m) < 1e-15:
                    return np.nan
                x = (y - b) / m
            elif model == "loglinear":
                m, b = popt
                if abs(m) < 1e-15:
                    return np.nan
                x = 10.0 ** ((y - b) / m)
            else:
                a, b, c, dd = popt[:4]
                g = popt[4] if model == "5pl" else 1.0
                denom = y - dd
                if abs(denom) < 1e-15 or abs(b) < 1e-15 or g <= 0:
                    return np.nan
                inner = ((a - dd) / denom) ** (1.0 / g) - 1.0
                if not np.isfinite(inner) or inner <= 0:
                    return np.nan
                x = c * inner ** (1.0 / b)
            return float(x) if np.isfinite(x) and x > 0 else np.nan
        except (ValueError, ZeroDivisionError, FloatingPointError, OverflowError):
            return np.nan

    # Recovery means back-calculated concentration / nominal concentration.
    back_std = np.asarray([back(float(y)) for y in sy], float)
    recovery = np.where(np.isfinite(back_std), back_std / sx * 100.0, np.nan)
    try:
        lo_r, hi_r = [float(v.strip()) for v in str(params.get("recovery_range", "80-120")).split("-", 1)]
    except Exception as exc:
        raise ValueError("Recovery range must look like '80-120'.") from exc
    if lo_r > hi_r:
        lo_r, hi_r = hi_r, lo_r
    bad_std = [{"conc": float(a), "od": float(b), "recovery": None if not np.isfinite(r) else float(r)}
               for a, b, r in zip(sx, sy, recovery)
               if not np.isfinite(r) or not (lo_r <= r <= hi_r)]

    # Replicate precision is assessed among wells at the same nominal standard
    # concentration.  Unknowns have no replicate identifier in the current schema.
    max_cv = float(params.get("max_cv", 15))
    rep_qc = []
    for conc in sorted(np.unique(sx)):
        vals = sy[sx == conc]
        if len(vals) < 2:
            continue
        mean = float(np.mean(vals))
        cv = float(np.std(vals, ddof=1) / abs(mean) * 100.0) if mean != 0 else float("inf")
        rep_qc.append({"conc": float(conc), "n": int(len(vals)), "od_cv": cv,
                       "flag": bool(cv > max_cv)})

    dil = float(params.get("dilution", 1) or 1)
    if dil <= 0:
        raise ValueError("Dilution factor must be greater than zero.")
    unknowns = []
    min_od, max_od = float(np.min(sy)), float(np.max(sy))
    for _, r in unk.iterrows():
        y = pd.to_numeric(pd.Series([r[od_c]]), errors="coerce").iloc[0]
        if not np.isfinite(y):
            continue
        val = back(float(y))
        unknowns.append({"label": str(r.get(well_c, "")) if well_c else "",
                         "od": float(y),
                         "concentration": None if not np.isfinite(val) else float(val * dil),
                         "in_range": bool(min_od <= y <= max_od)})

    model_label = {"4pl": "4PL", "5pl": "5PL", "linear": "Linear",
                   "loglinear": "Log-linear"}[model]
    if model in {"4pl", "5pl"}:
        parameters = {"a_low_asymptote": float(popt[0]), "b_hill": float(popt[1]),
                      "c_ec50": float(popt[2]), "d_high_asymptote": float(popt[3])}
        if model == "5pl":
            parameters["g_asymmetry"] = float(popt[4])
    else:
        parameters = {"slope": float(popt[0]), "intercept": float(popt[1])}

    if model == "linear":
        curve_x = np.linspace(float(sx.min()), float(sx.max()), 120)
    else:
        curve_x = np.logspace(math.log10(max(float(sx.min()), 1e-12)),
                              math.log10(float(sx.max())), 120)

    out = {"kind": "elisa", "test": f"{model_label} standard curve",
           "model": model, "parameters": parameters,
           "r_squared": float(r2), "weighting": weight,
           "standards": [{"conc": float(a), "od": float(b), "fitted": float(c),
                          "back_calculated": None if not np.isfinite(bc) else float(bc),
                          "recovery": None if not np.isfinite(r) else float(r)}
                         for a, b, c, bc, r in zip(sx, sy, pred, back_std, recovery)],
           "replicate_qc": rep_qc, "max_cv": max_cv,
           "unknowns": unknowns,
           "n_out_of_range": sum(1 for u in unknowns if not u["in_range"]),
           "recovery_failures": bad_std,
           "curve": [{"x": float(x), "y": float(fn(x, *popt))} for x in curve_x]}
    warn = []
    if np.isfinite(r2) and r2 < 0.98:
        warn.append(f"Curve R² = {r2:.4f}. Check whether the selected model and standards adequately describe the assay response.")
    if bad_std:
        warn.append(f"{len(bad_std)} standard wells fall outside {lo_r:.0f}-{hi_r:.0f}% back-calculated recovery.")
    bad_cv = [x for x in rep_qc if x["flag"]]
    if bad_cv:
        warn.append(f"{len(bad_cv)} standard concentration levels exceed the {max_cv:g}% replicate OD CV threshold.")
    if out["n_out_of_range"]:
        warn.append(f"{out['n_out_of_range']} unknowns fall outside the observed standard OD range; their concentrations are extrapolated.")
    if warn:
        out["warning"] = " ".join(warn)

    if params.get("edge_effect") and well_c:
        wells = unk[well_c].astype(str).str.strip().str.upper()
        rowsl = wells.str[0]
        colsn = pd.to_numeric(wells.str[1:], errors="coerce")
        # Infer 96-vs-384 dimensions from observed well coordinates where possible.
        max_col = int(colsn.max()) if colsn.notna().any() else 12
        last_row = chr(ord("A") + (15 if max_col > 12 else 7))
        edge = (rowsl.isin(["A", last_row])) | (colsn.isin([1, 24 if max_col > 12 else 12]))
        inner = ~edge
        if edge.sum() > 2 and inner.sum() > 2:
            a = pd.to_numeric(unk.loc[edge.values, od_c], errors="coerce").dropna()
            b = pd.to_numeric(unk.loc[inner.values, od_c], errors="coerce").dropna()
            if len(a) > 1 and len(b) > 1:
                st = stats.ttest_ind(a, b, equal_var=False)
                out["edge_effect"] = {"edge_mean": float(a.mean()),
                                      "inner_mean": float(b.mean()),
                                      "p": float(st.pvalue),
                                      "note": ("Edge wells differ from inner wells; evaporation or temperature gradient may be present."
                                               if st.pvalue < 0.05 else
                                               "No detectable edge effect.")}
    return out


# ─── Dimensionality reduction

# ─── Dimensionality reduction ────────────────────────────────────────────

def dimreduction(df, roles, params, ctl=None):
    cols = roles.get("vars", [])
    colour = _one(roles, "colour")
    sub = df[cols].apply(pd.to_numeric, errors="coerce")
    keep = sub.notna().all(axis=1)
    X = sub[keep].values
    labels = df.loc[keep, colour].astype(str).tolist() if colour else None
    if params.get("scale", True):
        X = (X - X.mean(0)) / np.where(X.std(0, ddof=1) == 0, 1, X.std(0, ddof=1))
    method = params.get("method", "pca")
    ncomp = int(params.get("components", 2))

    if method == "pca":
        U, S, Vt = np.linalg.svd(X - X.mean(0), full_matrices=False)
        scores = U[:, :ncomp] * S[:ncomp]
        var = (S**2) / (len(X) - 1)
        explained = (var / var.sum() * 100)
        return {"kind": "embedding", "method": "PCA", "n": int(len(X)),
                "points": [{"x": float(a), "y": float(b),
                            "label": labels[i] if labels else None}
                           for i, (a, b) in enumerate(scores[:, :2])],
                "explained": explained[:min(10, len(explained))].round(2).tolist(),
                "cumulative": np.cumsum(explained)[:10].round(2).tolist(),
                "loadings": [{"variable": c,
                              "pc1": float(Vt[0, j]), "pc2": float(Vt[1, j])}
                             for j, c in enumerate(cols)],
                "axis_labels": [f"PC1 ({explained[0]:.1f}%)", f"PC2 ({explained[1]:.1f}%)"]}

    if not have("sklearn"):
        raise ValueError("This method needs scikit-learn. pip install scikit-learn")
    if method == "tsne":
        from sklearn.manifold import TSNE
        emb = TSNE(n_components=2, perplexity=float(params.get("perplexity", 30)),
                   random_state=get("seed", 0), init="pca").fit_transform(X)
        name = "t-SNE"
    elif method == "umap":
        if not have("umap"):
            raise ValueError("UMAP needs umap-learn. pip install umap-learn")
        import umap
        emb = umap.UMAP(random_state=get("seed", 0)).fit_transform(X)
        name = "UMAP"
    else:
        from sklearn.manifold import MDS
        emb = MDS(n_components=2, random_state=get("seed", 0)).fit_transform(X)
        name = "MDS"
    return {"kind": "embedding", "method": name, "n": int(len(X)),
            "points": [{"x": float(a), "y": float(b),
                        "label": labels[i] if labels else None}
                       for i, (a, b) in enumerate(emb)],
            "axis_labels": [f"{name} 1", f"{name} 2"],
            "caveat": "Distances between clusters in a neighbour embedding are not "
                      "meaningful. Do not read separation as effect size."}


# ─── Equivalence ─────────────────────────────────────────────────────────

def tost(df, roles, params, ctl=None):
    dv, group = _one(roles, "dv"), _one(roles, "group")
    g = [(str(l), pd.to_numeric(s[dv], errors="coerce").dropna().values)
         for l, s in df.groupby(group, dropna=True, observed=True)]
    if len(g) != 2:
        raise ValueError("TOST here compares exactly two groups.")
    (l1, a), (l2, b) = g
    lo = float(params.get("lower", -0.5)); hi = float(params.get("upper", 0.5))
    alpha = float(params.get("alpha", 0.05))
    if params.get("bound_type") == "d":
        sp = math.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
        lo, hi = lo * sp, hi * sp
    diff = a.mean() - b.mean()
    se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    dof = ((a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)) ** 2 /
           ((a.var(ddof=1) / len(a)) ** 2 / (len(a) - 1) +
            (b.var(ddof=1) / len(b)) ** 2 / (len(b) - 1)))
    t1 = (diff - lo) / se
    t2 = (diff - hi) / se
    p1 = float(stats.t.sf(t1, dof))
    p2 = float(stats.t.cdf(t2, dof))
    p = max(p1, p2)
    tcrit = stats.t.ppf(1 - alpha, dof)
    return {"kind": "equivalence", "test": "Two one-sided tests (TOST)",
            "levels": [l1, l2], "n": [len(a), len(b)],
            "mean": [float(a.mean()), float(b.mean())],
            "mean_diff": float(diff),
            "bounds": [lo, hi],
            "tost_ci": [float(diff - tcrit * se), float(diff + tcrit * se)],
            "p_lower": p1, "p_upper": p2, "p": p,
            "equivalent": bool(p < alpha),
            "sentence": (f"Difference {diff:.3f}, {int((1-2*alpha)*100)}% TOST interval "
                         f"[{diff - tcrit*se:.3f}, {diff + tcrit*se:.3f}], {fmt_p(p)}"),
            "interpretation": ("The difference is statistically within the equivalence "
                               "margin." if p < alpha else
                               "Equivalence is not established. This is not the same as "
                               "a difference being present.")}


def noninferiority(df, roles, params, ctl=None):
    out_c, group = _one(roles, "outcome"), _one(roles, "group")
    g = [(str(l), s[out_c]) for l, s in df.groupby(group, dropna=True, observed=True)]
    if len(g) != 2:
        raise ValueError("Needs exactly two groups.")
    (l1, a), (l2, b) = g
    margin = float(params.get("margin", 0.1))
    alpha = float(params.get("alpha", 0.025))
    measure = params.get("measure", "mean_diff")
    higher_better = params.get("direction", "higher") == "higher"
    if measure == "mean_diff":
        a = pd.to_numeric(a, errors="coerce").dropna().values
        b = pd.to_numeric(b, errors="coerce").dropna().values
        diff = a.mean() - b.mean()
        se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
        va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
        dof = (va + vb) ** 2 / (va**2 / (len(a) - 1) + vb**2 / (len(b) - 1))
        crit = stats.t.ppf(1 - alpha, dof)
        lo, hi = diff - crit * se, diff + crit * se
        conclusion = (lo > -margin) if higher_better else (hi < margin)
    else:
        av = pd.to_numeric(a, errors="coerce").dropna()
        bv = pd.to_numeric(b, errors="coerce").dropna()
        p1, p2 = av.mean(), bv.mean()
        diff = p1 - p2
        se = math.sqrt(p1 * (1 - p1) / len(av) + p2 * (1 - p2) / len(bv))
        z = stats.norm.ppf(1 - alpha)
        lo, hi = diff - z * se, diff + z * se
        conclusion = (lo > -margin) if higher_better else (hi < margin)
    return {"kind": "equivalence", "test": "Non-inferiority",
            "levels": [l1, l2], "measure": measure, "margin": margin,
            "estimate": float(diff), "ci": [float(lo), float(hi)],
            "one_sided_alpha": alpha,
            "non_inferior": bool(conclusion),
            "interpretation": ("Non-inferiority established at the stated margin."
                               if conclusion else
                               "Non-inferiority not established; the interval crosses "
                               "the margin."),
            "note": "The margin must be pre-specified and clinically justified. "
                    "Choosing it after seeing the data invalidates the conclusion."}


def cluster_adjust(df, roles, params, ctl=None):
    out_c, cl_c = _one(roles, "outcome"), _one(roles, "cluster")
    sub = df[[out_c, cl_c]].dropna()
    y = pd.to_numeric(sub[out_c], errors="coerce")
    sub = sub.assign(_y=y).dropna(subset=["_y"])
    groups = sub.groupby(cl_c, observed=True)["_y"]
    k = groups.ngroups
    n = len(sub)
    m = n / k if k else np.nan
    grand = sub["_y"].mean()
    ms_b = groups.apply(lambda s: len(s) * (s.mean() - grand) ** 2).sum() / (k - 1) if k > 1 else np.nan
    ms_w = groups.apply(lambda s: ((s - s.mean()) ** 2).sum()).sum() / (n - k) if n > k else np.nan
    icc = float((ms_b - ms_w) / (ms_b + (m - 1) * ms_w)) if ms_b == ms_b and (ms_b + (m - 1) * ms_w) else np.nan
    deff = 1 + (m - 1) * icc if icc == icc else np.nan
    out = {"kind": "single", "test": "Cluster adjustment",
           "n_clusters": int(k), "n_total": int(n), "mean_cluster_size": float(m),
           "design_effect": float(deff),
           "effective_n": float(n / deff) if deff and deff == deff else None,
           "interpretation": (f"Treating these {n} observations as independent overstates "
                              f"the sample size by a factor of {deff:.2f}. The effective "
                              f"sample size is about {n/deff:.0f}."
                              if deff == deff else "Could not estimate the design effect.")}
    if params.get("report_icc", True):
        out["icc"] = icc
    return out


RUNNERS = {
    "qpcr": qpcr, "elisa": elisa, "dimreduction": dimreduction,
    "tost": tost, "noninferiority": noninferiority, "cluster_adjust": cluster_adjust,
}
