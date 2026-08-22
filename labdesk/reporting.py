"""
Reporting.

Three things come out of here:

  Results sentences, formatted correctly and consistently. Reviewers notice
  when F(2,57) is written three different ways in one paper.

  A methods paragraph assembled from the provenance ledger, so it describes
  what was actually run, including the corrections and the software versions.

  Reporting checklists, and a reproducible bundle containing the data hash,
  the specs, the results, the figures and generated scripts.
"""

import json
import os
import time
import zipfile

from . import db
from .config import EXPORT_DIR, get
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


# ─────────────────────────────────────────────────────────────────────────
#  Reporting checklists
# ─────────────────────────────────────────────────────────────────────────

CHECKLISTS = {
    "consort": {"label": "CONSORT 2010 (randomised trials)", "items": [
        "Title identifies the study as randomised",
        "Structured abstract with trial design, methods, results and conclusions",
        "Scientific background and rationale",
        "Specific objectives or hypotheses",
        "Trial design including allocation ratio",
        "Eligibility criteria and settings",
        "Interventions with sufficient detail to allow replication",
        "Completely defined pre-specified primary and secondary outcomes",
        "How sample size was determined",
        "Method used to generate the random allocation sequence",
        "Allocation concealment mechanism",
        "Who was blinded after assignment",
        "Statistical methods for primary and secondary outcomes",
        "Participant flow diagram",
        "Dates defining recruitment and follow-up",
        "Baseline demographic and clinical characteristics table",
        "Numbers analysed in each group",
        "Results for each outcome with effect size and precision",
        "Results of any subgroup or adjusted analyses, marked as exploratory",
        "All important harms or unintended effects",
        "Trial limitations",
        "Registration number and name of registry",
        "Where the full protocol can be accessed",
        "Sources of funding and role of funders",
    ]},
    "strobe": {"label": "STROBE (observational studies)", "items": [
        "Study design stated in the title or abstract",
        "Scientific background and rationale",
        "Specific objectives including any pre-specified hypotheses",
        "Key elements of study design",
        "Setting, locations and relevant dates",
        "Eligibility criteria and methods of selection",
        "Clearly defined outcomes, exposures, predictors and confounders",
        "Sources of data and details of assessment methods",
        "Efforts to address potential sources of bias",
        "How study size was arrived at",
        "How quantitative variables were handled and why groupings were chosen",
        "Statistical methods including control of confounding",
        "Methods for subgroups and interactions",
        "How missing data were addressed",
        "Numbers at each stage with a flow diagram",
        "Characteristics of participants and missing data per variable",
        "Unadjusted and confounder-adjusted estimates with precision",
        "Sensitivity analyses",
        "Key results with reference to objectives",
        "Limitations including direction and magnitude of potential bias",
        "Generalisability",
        "Source of funding and role of funders",
    ]},
    "prisma": {"label": "PRISMA 2020 (systematic reviews)", "items": [
        "Title identifies the report as a systematic review",
        "Abstract following the PRISMA abstract checklist",
        "Rationale in the context of existing knowledge",
        "Explicit statement of objectives with a PICO question",
        "Inclusion and exclusion criteria and how studies were grouped",
        "All databases, registers and other sources with dates last searched",
        "Full search strategy for at least one database",
        "Selection process including number of reviewers and any automation",
        "Data collection process",
        "List and definition of all outcomes sought",
        "Methods to assess risk of bias including number of reviewers",
        "Effect measures used for each outcome",
        "Synthesis methods, including handling of missing summary statistics",
        "Methods to assess reporting bias",
        "Methods to assess certainty of evidence (GRADE)",
        "Flow diagram with numbers at each stage and reasons for exclusion",
        "Characteristics table for each included study",
        "Risk of bias assessments for each study",
        "Results of each individual study",
        "Results of all syntheses with heterogeneity statistics",
        "Assessments of reporting bias",
        "Certainty of evidence for each outcome",
        "Discussion of limitations of the evidence and of the review process",
        "Registration number and protocol location",
        "Sources of financial support and competing interests",
        "Availability of data, code and other materials",
    ]},
    "stard": {"label": "STARD 2015 (diagnostic accuracy)", "items": [
        "Title identifies the article as a study of diagnostic accuracy",
        "Structured abstract with estimates of accuracy and precision",
        "Scientific and clinical background",
        "Study objectives and hypotheses",
        "Whether data collection was prospective or retrospective",
        "Eligibility criteria and how participants were identified",
        "Index test and reference standard described in sufficient detail",
        "Rationale for choosing the reference standard",
        "Definition and rationale for test positivity cut-offs",
        "Whether assessors were blinded",
        "Methods for estimating diagnostic accuracy and handling indeterminate results",
        "How sample size was determined",
        "Flow of participants with a diagram",
        "Distribution of severity of disease and alternative diagnoses",
        "Cross-tabulation of index test against the reference standard",
        "Estimates of accuracy with confidence intervals",
        "Any adverse events from the index test",
        "Study limitations including sources of bias and uncertainty",
        "Implications for practice",
        "Registration number and where the protocol can be accessed",
    ]},
    "arrive": {"label": "ARRIVE 2.0 (animal research)", "items": [
        "Species, strain, sex, age and weight of animals",
        "Total number of animals and number per group",
        "How sample size was decided",
        "Inclusion and exclusion criteria specified a priori",
        "Randomisation method and what was randomised",
        "Blinding at allocation, conduct and outcome assessment",
        "Precisely defined outcome measures",
        "Full statistical methods including unit of analysis",
        "Experimental animals: source, housing, husbandry, welfare",
        "Experimental procedures in replicable detail",
        "Results for each analysis with a measure of precision",
        "Any adverse events",
        "Ethical approval and licence details",
        "Data availability statement",
    ]},
    "tripod": {"label": "TRIPOD (prediction models)", "items": [
        "Title identifies development, validation, or both",
        "Source of data and separation of development and validation sets",
        "Participants, setting and eligibility",
        "Outcome definition and blinding of outcome assessment",
        "All predictors with definitions and timing of measurement",
        "Sample size and how it was arrived at",
        "How missing data were handled",
        "How predictors were handled in the analysis",
        "Type of model, all model-building steps and internal validation",
        "Measures of model performance including calibration",
        "Flow of participants with numbers analysed",
        "Characteristics of participants including predictor distributions",
        "Full model presented so a reader can make predictions",
        "Model performance with confidence intervals",
        "Limitations including overfitting and non-representative sampling",
        "Funding and availability of supplementary resources",
    ]},
    "spirit": {"label": "SPIRIT 2013 (trial protocols)", "items": [
        "Descriptive title identifying design, population, interventions and acronym",
        "Trial registration and all World Health Organization data set items",
        "Protocol version and date",
        "Funding sources and roles",
        "Background, rationale and explanation for the choice of comparators",
        "Specific objectives or hypotheses",
        "Trial design including allocation ratio and framework",
        "Study setting and eligibility criteria",
        "Interventions with criteria for discontinuation and adherence strategies",
        "Primary, secondary and other outcomes with metric and timing",
        "Participant timeline diagram",
        "Sample size calculation",
        "Allocation sequence generation, concealment and implementation",
        "Blinding and circumstances for unblinding",
        "Data collection, management and quality control",
        "Statistical methods including additional and missing-data analyses",
        "Data monitoring committee and interim analyses",
        "Harms collection and reporting",
        "Auditing",
        "Research ethics approval and consent procedures",
        "Confidentiality and declaration of interests",
        "Dissemination policy and authorship criteria",
    ]},
}


def checklist(kind):
    c = CHECKLISTS.get(kind)
    if not c:
        raise ValueError(f"No checklist named {kind!r}.")
    return {"id": kind, "label": c["label"],
            "items": [{"n": i + 1, "text": t} for i, t in enumerate(c["items"])]}


# ─────────────────────────────────────────────────────────────────────────
#  Reproducibility bundle
# ─────────────────────────────────────────────────────────────────────────

def bundle(dataset_id=None, include_data=True, project_id=None):
    from . import datasets
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(EXPORT_DIR, f"labdesk_bundle_{ts}.zip")
    m = datasets.meta(dataset_id) if dataset_id else None
    if m and project_id is None:
        project_id = m.get("project_id")
    if m and m.get("project_id") != project_id:
        raise ValueError("That dataset does not belong to the requested project.")
    sql = "SELECT * FROM analysis_run WHERE status='ok' AND project_id IS ?"
    args = (project_id,)
    if m:
        sql += " AND dataset_id=?"
        args += (dataset_id,)
    runs = db.query(sql + " ORDER BY created_at ASC", args)

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        manifest = {
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "dataset": {"name": m["name"], "sha256": m["sha256"],
                        "n_rows": m["n_rows"], "n_cols": m["n_cols"]} if m else None,
            "project_id": project_id,
            "n_runs": len(runs),
            "seeds": sorted({r.get("seed") for r in runs if r.get("seed") is not None}),
            "alphas": sorted({r.get("alpha") for r in runs if r.get("alpha") is not None}),
            "versions": [json.loads(r.get("versions") or "{}") for r in runs],
        }
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("README.txt",
                   "LabDesk reproducibility bundle\n\n"
                   "The JSON files under runs/ are the canonical ledger records: executed method, "
                   "parameters, assumptions and result. reproduce.py and reproduce.R contain emitted "
                   "analysis snippets; not every statistical family can yet be represented as a fully "
                   "standalone script, so verify each snippet against its run JSON before execution.\n")
        z.writestr("methods.txt", methods_paragraph(m["sha256"] if m else None,
                                                   project_id=project_id)["text"])

        py_lines = ["# Analysis snippets emitted for the runs in this bundle.",
                    "# The run JSON files are the canonical provenance record; snippets may require",
                    "# the role variables named in each spec to be prepared from data.csv first.",
                    "import pandas as pd", "from scipy import stats",
                    "df = pd.read_csv('data.csv')", ""]
        r_lines = ["# R analysis snippets emitted for the runs in this bundle.",
                   "# See runs/*.json for the canonical executed specifications.",
                   "d <- read.csv('data.csv')", ""]
        for i, r in enumerate(runs, 1):
            spec = json.loads(r["spec"] or "{}")
            res = json.loads(r["result"] or "{}")
            z.writestr(f"runs/{i:03d}_{r['test_id']}.json",
                       json.dumps({"spec": spec, "result": res,
                                   "assumptions": json.loads(r["assumptions"] or "[]"),
                                   "created_at": r["created_at"]}, indent=2, default=str))
            py_lines += [f"# [{i}] {r['test_id']}", r["code_python"] or "", ""]
            r_lines += [f"# [{i}] {r['test_id']}", r["code_r"] or "", ""]
        z.writestr("reproduce.py", "\n".join(py_lines))
        z.writestr("reproduce.R", "\n".join(r_lines))

        run_ids = [r["id"] for r in runs]
        figs = []
        if run_ids:
            marks = ",".join("?" for _ in run_ids)
            figs = db.query(f"SELECT * FROM figure WHERE project_id IS ? AND run_id IN ({marks}) "
                            "ORDER BY created_at DESC LIMIT 200", (project_id, *run_ids))
        for f in figs:
            if f["path"] and os.path.exists(f["path"]):
                z.write(f["path"], f"figures/{os.path.basename(f['path'])}")

        if include_data and m and os.path.exists(m["path"]):
            try:
                datasets.load(dataset_id).to_csv(
                    os.path.join(EXPORT_DIR, "_tmp_data.csv"), index=False)
                z.write(os.path.join(EXPORT_DIR, "_tmp_data.csv"), "data.csv")
                os.remove(os.path.join(EXPORT_DIR, "_tmp_data.csv"))
            except Exception:
                pass

    return {"path": path, "n_runs": len(runs),
            "size_kb": round(os.path.getsize(path) / 1024, 1)}


def prereg_draft(question="", outcomes="", hypotheses=""):
    """A pre-registration skeleton in the OSF style."""
    return {"text": f"""Title

Research question
{question or '[State the question in PICO form.]'}

Hypotheses
{hypotheses or '[State each hypothesis and its direction. Anything not listed here is exploratory.]'}

Design
[Design, allocation, blinding, and the unit of analysis.]

Sampling plan
[Target sample size, the calculation that produced it, and the stopping rule.
If data collection has already begun, say so and say how much.]

Variables
Primary outcome: {outcomes or '[one outcome]'}
Secondary outcomes: [list]
Covariates: [list]

Analysis plan
Primary analysis: [test, with the exact model specification]
Assumption checks and what happens if they fail: [pre-specify the fallback]
Multiple comparisons: correction across [family], using [method]
Missing data: [approach]
Outliers: [rule, decided now, not later]
Inference criteria: alpha = {get('alpha', 0.05)}, two-sided

Exploratory analyses
[Anything not listed above is exploratory and will be labelled as such.]

Data and code availability
[Where the data, the analysis code and the materials will be deposited.]""",
            "note": "Pre-registration is worth more than any statistical correction. "
                    "The fallback for a failed assumption is the field people forget, "
                    "and it is the one that stops a p-hack from looking principled."}
