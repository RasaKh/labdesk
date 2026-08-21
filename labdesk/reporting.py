"""
Reporting.

Results sentences, a methods paragraph assembled from the provenance
ledger, reporting checklists, and a reproducible bundle.
"""

import json

from .config import get
from .stats_run import fmt_n, fmt_p, versions


# ─────────────────────────────────────────────────────────────────────────
#  Results sentences
# ─────────────────────────────────────────────────────────────────────────

def _p_text(p, style):
    if p is None:
        return ""
    t = fmt_p(p, style)
    return t if style == "apa" else t.replace("p", "P")

def sentence(result, style=None):
    style = style or get("stats_report_style", "apa")
    d = get("decimals", 3)
    k = result.get("kind")
    p = result.get("p")

    if k == "comparison":
        lv = result.get("levels", ["group 1", "group 2"])
        if result.get("mean"):
            a = (f"{lv[0]} (mean {fmt_n(result['mean'][0])}"
                 + (f", SD {fmt_n(result['sd'][0])}" if result.get("sd") else "") + ")")
            b = (f"{lv[1]} (mean {fmt_n(result['mean'][1])}"
                 + (f", SD {fmt_n(result['sd'][1])}" if result.get("sd") else "") + ")")
        else:
            a = f"{lv[0]} (median {fmt_n((result.get('median') or [0])[0])})"
            b = f"{lv[1]} (median {fmt_n((result.get('median') or [0, 0])[1])})"
        core = ""
        if result.get("statistic") is not None:
            if "t-test" in str(result.get("test", "")):
                core = f"t({fmt_n(result.get('df'), 1)}) = {fmt_n(result['statistic'], 2)}, "
            elif "Mann-Whitney" in str(result.get("test", "")):
                core = f"U = {result['statistic']:.0f}, "
            else:
                core = f"statistic = {fmt_n(result['statistic'], 2)}, "
        eff = result.get("effects") or {}
        es = ""
        if eff.get("hedges_g") is not None:
            es = f", Hedges g = {fmt_n(eff['hedges_g'], 2)}"
        elif eff.get("cohen_dz") is not None:
            es = f", dz = {fmt_n(eff['cohen_dz'], 2)}"
        elif eff.get("rank_biserial") is not None:
            es = f", rank-biserial r = {fmt_n(eff['rank_biserial'], 2)}"
        ci = ""
        if result.get("diff_ci"):
            ci = (f" (difference {fmt_n(result.get('mean_diff'))}, "
                  f"{int(get('ci_level', .95)*100)}% CI {fmt_n(result['diff_ci'][0])} to "
                  f"{fmt_n(result['diff_ci'][1])})")
        return (f"{a} differed from {b}{ci}; {core}{_p_text(p, style)}{es}.")

    if k == "anova":
        df = result.get("df") or []
        if "Kruskal" in str(result.get("test")):
            return (f"A Kruskal-Wallis test showed "
                    f"H({df[0] if df else ''}) = {fmt_n(result['statistic'], 2)}, "
                    f"{_p_text(p, style)}.")
        eff = result.get("effects") or {}
        es = ""
        for key, lab in (("partial_eta_squared", "partial η²"), ("eta_squared", "η²"),
                         ("omega_squared", "ω²"), ("epsilon_squared", "ε²")):
            if eff.get(key) is not None:
                es = f", {lab} = {fmt_n(eff[key], 2)}"
                break
        def fmt_df(v):
            return str(int(v)) if float(v).is_integer() else fmt_n(v, 2)
        dfs = f"({fmt_df(df[0])}, {fmt_df(df[1])})" if len(df) > 1 else (
            f"({fmt_df(df[0])})" if df else "")
        return (f"{result.get('test')} showed F{dfs} = {fmt_n(result['statistic'], 2)}, "
                f"{_p_text(p, style)}{es}.")

    if k == "categorical":
        return (f"{result.get('test')}: χ²({result.get('df', '')}) = "
                f"{fmt_n(result.get('statistic'), 2)}, {_p_text(p, style)}"
                + (f", Cramér's V = {fmt_n((result.get('effects') or {}).get('cramers_v'), 2)}"
                   if (result.get("effects") or {}).get("cramers_v") is not None else "")
                + f" (n = {result.get('n')}).")

    if k == "correlation":
        rows = result.get("rows") or []
        if not rows:
            return ""
        r0 = rows[0]
        return (f"{result.get('method', 'Pearson').title()} correlation between "
                f"{r0['a']} and {r0['b']} was r = {fmt_n(r0['r'], 2)} "
                f"({int(get('ci_level', .95)*100)}% CI {fmt_n(r0['ci'][0], 2)} to "
                f"{fmt_n(r0['ci'][1], 2)}), {_p_text(r0.get('p'), style)}, n = {r0['n']}.")

    if k == "regression":
        if "Poisson" in str(result.get("test")) or "Negative binomial" in str(result.get("test")):
            terms = [c for c in result.get("coefficients", []) if c["term"] != "(Intercept)"]
            bits = [f"{c['term']}: IRR {fmt_n(c['estimate'], 2)} "
                    f"({fmt_n(c['ci'][0], 2)} to {fmt_n(c['ci'][1], 2)}), "
                    f"{_p_text(c['p'], style)}" for c in terms[:6]]
            return (f"{result.get('test')} on {result.get('n')} observations "
                    f"({result.get('n_events')} events): " + "; ".join(bits) + ".")
        if "Logistic" in str(result.get("test")):
            terms = [c for c in result.get("coefficients", []) if c["term"] != "(Intercept)"]
            bits = [f"{c['term']}: OR {fmt_n(c['estimate'], 2)} "
                    f"({fmt_n(c['ci'][0], 2)} to {fmt_n(c['ci'][1], 2)}), "
                    f"{_p_text(c['p'], style)}" for c in terms[:6]]
            return (f"Logistic regression on {result.get('n')} observations with "
                    f"{result.get('n_events')} events: " + "; ".join(bits) + ".")
        return (f"Linear regression explained {fmt_n(result.get('r_squared'), 3)} of the "
                f"variance (adjusted R² = {fmt_n(result.get('adj_r_squared'), 3)}, "
                f"n = {result.get('n')}).")

    if k == "cox":
        terms = result.get("coefficients", [])
        bits = [f"{c['term']}: HR {fmt_n(c['estimate'], 2)} "
                f"({fmt_n(c['ci'][0], 2)} to {fmt_n(c['ci'][1], 2)}), "
                f"{_p_text(c['p'], style)}" for c in terms[:6]]
        return (f"Cox proportional hazards model on {result.get('n')} observations with "
                f"{result.get('n_events')} events: " + "; ".join(bits)
                + f"; concordance {fmt_n((result.get('effects') or {}).get('concordance'), 2)}.")

    if k == "survival":
        parts = []
        for c in result.get("curves", []):
            med = "not reached" if c.get("median") is None else fmt_n(c["median"], 1)
            parts.append(f"{c['label']}: median {med} (n = {c['n']}, {c['events']} events)")
        s = "; ".join(parts)
        if result.get("p") is not None:
            s += f". Log-rank χ²({result.get('df')}) = {fmt_n(result['statistic'], 2)}, " \
                 f"{_p_text(result['p'], style)}"
        return s + "."

    if k == "roc":
        ci = result.get("auc_ci")
        return (f"The area under the ROC curve was {fmt_n(result.get('auc'), 3)}"
                + (f" ({int(get('ci_level', .95)*100)}% CI {fmt_n(ci[0], 3)} to "
                   f"{fmt_n(ci[1], 3)})" if ci else "")
                + (f". At a threshold of {fmt_n(result['best']['threshold'])}, sensitivity "
                   f"was {result['best']['sensitivity']:.1%} and specificity "
                   f"{result['best']['specificity']:.1%}" if result.get("best") else "") + ".")

    if k == "meta":
        h = result.get("heterogeneity", {})
        return (f"Pooling {result.get('k')} studies with a "
                f"{str(result.get('model','')).lower()} model gave a "
                f"{result.get('measure')} of {fmt_n(result.get('pooled'), 2)} "
                f"({int(get('ci_level', .95)*100)}% CI {fmt_n(result['pooled_ci'][0], 2)} to "
                f"{fmt_n(result['pooled_ci'][1], 2)}), {_p_text(result.get('p'), style)}. "
                f"Heterogeneity was I² = {h.get('I2', 0):.0f}% "
                f"(τ² = {fmt_n(h.get('tau2'), 3)}, Q({h.get('df')}) = "
                f"{fmt_n(h.get('Q'), 2)}, {_p_text(h.get('p'), style)}).")

    if k == "equivalence":
        return result.get("interpretation", "")

    return result.get("sentence", "")

# ─────────────────────────────────────────────────────────────────────────
#  Methods paragraph
# ─────────────────────────────────────────────────────────────────────────

TEST_METHOD_NAMES = {
    "ttest_ind": "independent-samples t tests",
    "ttest_paired": "paired t tests",
    "mannwhitney": "Mann-Whitney U tests",
    "wilcoxon": "Wilcoxon signed-rank tests",
    "anova_oneway": "one-way analysis of variance",
    "welch_anova": "Welch's analysis of variance",
    "kruskal": "Kruskal-Wallis tests",
    "friedman": "Friedman tests",
    "chi2": "chi-square tests of independence",
    "fisher": "Fisher's exact tests",
    "correlation": "correlation analysis",
    "linreg": "linear regression",
    "logreg": "logistic regression",
    "kaplan_meier": "Kaplan-Meier survival analysis with log-rank tests",
    "roc": "receiver operating characteristic analysis",
    "meta_effect": "random-effects meta-analysis",
    "icc": "intraclass correlation",
    "bland_altman": "Bland-Altman agreement analysis",
    "tost": "equivalence testing by two one-sided tests",
    "qpcr": "relative quantification of gene expression",
    "elisa": "ELISA standard-curve fitting",
}

def methods_paragraph(dataset_sha=None, limit=200, project_id=None):
    sql = "SELECT * FROM analysis_run WHERE status='ok' AND project_id IS ?"
    args = (project_id,)
    if dataset_sha:
        sql += " AND dataset_sha=?"
        args += (dataset_sha,)
    sql += " ORDER BY created_at ASC LIMIT ?"
    runs = db.query(sql, args + (limit,))
    if not runs:
        return {"text": "No analyses have been run yet.", "n_runs": 0}

    used = []
    for r in runs:
        name = TEST_METHOD_NAMES.get(r["test_id"], r["test_id"].replace("_", " "))
        if name not in used:
            used.append(name)

    corrections = set()
    for r in runs:
        try:
            spec = json.loads(r["spec"] or "{}")
            c = (spec.get("params") or {}).get("correction")
            if c and c != "none":
                corrections.add({"holm": "Holm's step-down procedure",
                                 "bonferroni": "Bonferroni correction",
                                 "fdr_bh": "the Benjamini-Hochberg false discovery rate procedure",
                                 "fdr_by": "the Benjamini-Yekutieli procedure",
                                 "sidak": "Šidák correction",
                                 "storey": "Storey q values"}.get(c, c))
        except Exception:
            pass

    assumption_note = ""
    checked = 0
    failed = 0
    for r in runs:
        try:
            for c in json.loads(r["assumptions"] or "[]"):
                checked += 1
                if c.get("state") == "fail":
                    failed += 1
        except Exception:
            pass
    if checked:
        assumption_note = (
            f" Assumptions were checked before each test ({checked} checks in total"
            + (f", {failed} of which were violated and are noted in the results"
               if failed else "") + ").")

    parsed_versions = []
    for r in runs:
        try:
            parsed_versions.append(json.loads(r.get("versions") or "{}"))
        except Exception:
            pass
    v = parsed_versions[0] if parsed_versions else versions()
    versions_varied = any(x != v for x in parsed_versions[1:])
    software = (f"Analyses were performed in Python {v.get('python','3')} using "
                f"SciPy {v.get('scipy','')}"
                + (f", statsmodels {v['statsmodels']}" if v.get("statsmodels") else "")
                + (f", pingouin {v['pingouin']}" if v.get("pingouin") else "")
                + (f", lifelines {v['lifelines']}" if v.get("lifelines") else "")
                + f" and pandas {v.get('pandas','')}.")

    alphas = sorted({float(r["alpha"]) for r in runs if r.get("alpha") is not None})
    alpha_text = (str(alphas[0]) if len(alphas) == 1 else
                  "/".join(str(a) for a in alphas) if alphas else "not retained in legacy ledger entries")
    alternatives = set()
    for r in runs:
        try:
            alt = (json.loads(r.get("spec") or "{}").get("params") or {}).get("alternative")
            if alt:
                alternatives.add(alt)
        except Exception:
            pass
    sided = ("Two-sided tests were used throughout" if not alternatives or alternatives == {"two-sided"}
             else "Alternative hypotheses were used as specified in the run ledger (" +
                  ", ".join(sorted(alternatives)) + ")")
    seeds = sorted({r.get("seed") for r in runs if r.get("seed") is not None})
    text = (
        f"Statistical analysis used {', '.join(used[:-1])}"
        + (f" and {used[-1]}" if len(used) > 1 else used[0] if used else "")
        + f". {sided} and the recorded significance threshold(s) were {alpha_text}. P values below the applicable threshold were "
        "considered statistically significant."
        + (f" Multiple comparisons were corrected using {' and '.join(sorted(corrections))}."
           if corrections else "")
        + assumption_note
        + f" {software}"
        + (" Package versions varied across runs; the exact versions are retained per ledger entry."
           if versions_varied else "")
        + ((" Random seed" + ("s " if len(seeds) > 1 else " ") +
            ", ".join(map(str, seeds)) +
            (" were" if len(seeds) > 1 else " was") +
            " retained for resampling procedures.")
           if seeds and any("bootstrap" in r["test_id"] or "permutation" in r["test_id"] for r in runs)
           else "")
    )
    return {"text": text, "n_runs": len(runs), "tests_used": used,
            "software": software, "versions": v,
            "note": "Generated from the run ledger, so it describes what was actually "
                    "executed. Read it before pasting it; it is a draft, not a fact."}
