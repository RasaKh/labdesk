"""Bench assays, dimensionality reduction, and equivalence testing."""

import math

import numpy as np
import pandas as pd
from scipy import stats

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

RUNNERS = {
    "qpcr": qpcr,
}
