"""
Spec compilation and execution.

The browser posts {test, dataset, roles, params}. Nothing else. This module
resolves the roles against the dataset, runs the declared assumption checks,
applies the gate policy, dispatches to a runner, computes effect sizes,
formats the numbers, emits equivalent Python and R, and writes one row to
the provenance ledger.

A runner never sees a request object and never formats anything for display.
It takes (df, roles, params, ctl) and returns a plain dict.
"""
import math
import time

import numpy as np
import pandas as pd

from . import assumptions as A
from . import datasets, db
from .config import get
from .schema import validate_spec
from .stats_registry import REGISTRY

def fmt_p(p, style=None):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "NA"
    style = style or get("stats_report_style", "apa")
    floor = get("p_min_display", 0.001)
    if p < floor:
        s = f"< {floor:g}".replace("0.", ".") if style == "apa" else f"< {floor:g}"
        return "p " + s
    d = get("p_decimals", 4)
    txt = f"{p:.{d}f}".rstrip("0").rstrip(".")
    if style == "apa" and txt.startswith("0."):
        txt = txt[1:]
    return "p = " + txt


def fmt_n(x, d=None):
    if x is None:
        return "NA"
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return "NA" if math.isnan(x) else ("∞" if x > 0 else "-∞")
    d = get("decimals", 3) if d is None else d
    return f"{x:.{d}f}"


def stars(p, thresholds=None, ns=None):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return ""
    for cutoff, mark in (thresholds or get("star_thresholds")):
        if p < cutoff:
            return mark
    return ns if ns is not None else get("ns_label", "ns")


def ci_str(lo, hi, level=None):
    level = level or get("ci_level", 0.95)
    return f"{int(level*100)}% CI [{fmt_n(lo)}, {fmt_n(hi)}]"
def cohen_d(a, b, paired=False, pooled=True):
    a = pd.Series(a).dropna().astype(float)
    b = pd.Series(b).dropna().astype(float)
    if paired:
        d = (pd.Series(a).reset_index(drop=True) - pd.Series(b).reset_index(drop=True)).dropna()
        return float(d.mean() / d.std(ddof=1)) if d.std(ddof=1) else float("nan")
    n1, n2 = len(a), len(b)
    s1, s2 = a.std(ddof=1), b.std(ddof=1)
    if pooled:
        sp = math.sqrt(((n1 - 1) * s1**2 + (n2 - 1) * s2**2) / max(1, n1 + n2 - 2))
    else:
        sp = math.sqrt((s1**2 + s2**2) / 2)
    return float((a.mean() - b.mean()) / sp) if sp else float("nan")


def hedges_g(a, b, paired=False):
    d = cohen_d(a, b, paired=paired)
    if paired:
        n = min(len(pd.Series(a).dropna()), len(pd.Series(b).dropna()))
        df = n - 1
    else:
        n = len(pd.Series(a).dropna()) + len(pd.Series(b).dropna())
        df = n - 2
    J = 1 - 3 / (4 * df - 1) if df > 1 else 1.0
    return float(d * J)


def d_ci(d, n1, n2, level=None):
    """Approximate noncentral interval via the standard error of d."""
    level = level or get("ci_level", 0.95)
    from scipy import stats
    se = math.sqrt((n1 + n2) / (n1 * n2) + d**2 / (2 * (n1 + n2)))
    z = stats.norm.ppf(1 - (1 - level) / 2)
    return d - z * se, d + z * se


def rank_biserial(a, b):
    a = pd.Series(a).dropna().astype(float).values
    b = pd.Series(b).dropna().astype(float).values
    if not len(a) or not len(b):
        return float("nan")
    gt = sum((x > y) for x in a for y in b) if len(a) * len(b) <= 4_000_000 else None
    if gt is None:
        from scipy import stats
        u = stats.mannwhitneyu(a, b, alternative="two-sided").statistic
        return float(2 * u / (len(a) * len(b)) - 1)
    eq = sum((x == y) for x in a for y in b)
    return float((gt + 0.5 * eq) * 2 / (len(a) * len(b)) - 1)


def cles(a, b):
    """Common language effect size: P(a random value from a exceeds one from b)."""
    a = pd.Series(a).dropna().astype(float).values
    b = pd.Series(b).dropna().astype(float).values
    if not len(a) or not len(b):
        return float("nan")
    if len(a) * len(b) > 4_000_000:
        m = a.mean() - b.mean()
        s = math.sqrt(a.var(ddof=1) + b.var(ddof=1))
        from scipy import stats
        return float(stats.norm.cdf(m / s)) if s else float("nan")
    return float(np.mean([(x > y) + 0.5 * (x == y) for x in a for y in b]))


def hodges_lehmann(a, b=None):
    a = np.asarray(pd.Series(a).dropna().astype(float))
    if b is None:
        walsh = [(a[i] + a[j]) / 2 for i in range(len(a)) for j in range(i, len(a))]
        return float(np.median(walsh))
    b = np.asarray(pd.Series(b).dropna().astype(float))
    if len(a) * len(b) > 4_000_000:
        return float(np.median(a) - np.median(b))
    return float(np.median([x - y for x in a for y in b]))


def eta_squared(ss_between, ss_total):
    return float(ss_between / ss_total) if ss_total else float("nan")


def omega_squared(ss_between, ss_within, df_between, ms_within, n):
    num = ss_between - df_between * ms_within
    den = ss_between + ss_within + ms_within
    return float(num / den) if den else float("nan")


def epsilon_squared(H, n):
    return float((H - 1) / (n - 1)) if n > 1 else float("nan")


def cramers_v(chi2, n, r, c):
    k = min(r - 1, c - 1)
    return float(math.sqrt(chi2 / (n * k))) if n and k else float("nan")


# ─────────────────────────────────────────────────────────────────────────
#  Multiplicity
# ─────────────────────────────────────────────────────────────────────────

def adjust_p(pvals, method="holm"):
    p = np.asarray([np.nan if v is None else float(v) for v in pvals], float)
    ok = ~np.isnan(p)
    out = np.full(p.shape, np.nan)
    x = p[ok]
    n = len(x)
    if n == 0:
        return out.tolist()
    order = np.argsort(x)
    ranked = x[order]
    if method in (None, "none"):
        adj = ranked
    elif method == "bonferroni":
        adj = np.minimum(1, ranked * n)
    elif method == "sidak":
        adj = 1 - (1 - ranked) ** n
    elif method == "holm":
        adj = np.maximum.accumulate(np.minimum(1, ranked * (n - np.arange(n))))
    elif method == "fdr_bh":
        adj = np.minimum.accumulate(
            (ranked * n / (np.arange(n) + 1))[::-1])[::-1]
        adj = np.minimum(1, adj)
    elif method == "fdr_by":
        c = np.sum(1.0 / (np.arange(n) + 1))
        adj = np.minimum.accumulate(
            (ranked * n * c / (np.arange(n) + 1))[::-1])[::-1]
        adj = np.minimum(1, adj)
    elif method == "storey":
        lam = 0.5
        pi0 = min(1.0, np.mean(x > lam) / (1 - lam))
        adj = np.minimum.accumulate(
            (ranked * n * pi0 / (np.arange(n) + 1))[::-1])[::-1]
        adj = np.minimum(1, adj)
    else:
        adj = ranked
    back = np.empty(n)
    back[order] = adj
    out[ok] = back
    return out.tolist()
def resolve(spec):
    ds_id = spec.get("dataset")
    df = datasets.load(ds_id) if ds_id else None
    roles = {}
    for k, v in (spec.get("roles") or {}).items():
        roles[k] = [v] if isinstance(v, str) else list(v or [])
    return df, roles


def _dataset_context(spec):
    """Resolve data and canonical project ownership for an analysis spec."""
    ds_id = spec.get("dataset")
    m = datasets.meta(ds_id) if ds_id else None
    if ds_id and not m:
        raise KeyError(f"No dataset {ds_id!r}.")
    df, roles = resolve(spec)
    requested_project = spec.get("project")
    project_id = m.get("project_id") if m else requested_project
    if m and requested_project is not None and requested_project != project_id:
        raise ValueError(
            f"Dataset {ds_id} belongs to project {project_id!r}, not {requested_project!r}. "
            "Switch projects or move the dataset before running the analysis."
        )
    return df, roles, m, project_id


def _ctx(df, entry, roles, params):
    """Flatten roles into the shape the assumption checkers expect."""
    ctx = {"df": df, "params": params, "predictors": roles.get("predictors", [])}
    for r in entry.get("roles", []):
        got = roles.get(r["id"], [])
        ctx[r["id"]] = got[0] if (r["max"] == 1 and got) else got
    if "row" in ctx and "col" in ctx and df is not None:
        try:
            ctx["table"] = pd.crosstab(df[ctx["row"]], df[ctx["col"]]).values
        except Exception:
            pass
    return ctx


def preflight(spec):
    entry = REGISTRY.get(spec.get("test"))
    if not entry:
        return {"ok": False, "errors": [f"Unknown test {spec.get('test')!r}."]}
    try:
        df, roles, m, project_id = _dataset_context(spec)
    except Exception as exc:
        return {"ok": False, "errors": [str(exc)], "checks": [],
                "status": entry["status"]}
    errors, params = validate_spec(entry, spec, df=df,
                                   dictionary=(m or {}).get("dictionary"))
    from .config import missing_deps
    miss = missing_deps(entry.get("deps"))
    if miss:
        errors.append("Needs " + ", ".join(miss) + ". Install it from the Settings pane.")
    checks = []
    if df is not None and not errors:
        checks = A.run_checks(entry.get("assumptions"), _ctx(df, entry, roles, params))
    allowed, action, msg = A.gate(checks) if checks else (True, "run", None)
    n_prior = 0
    if m:
        n_prior = db.runs_on_dataset(m["sha256"], project_id)
    return {
        "ok": not errors and allowed,
        "errors": errors,
        "checks": checks,
        "verdict": A.verdict(checks) if checks else "pass",
        "action": action,
        "message": msg,
        "status": entry["status"],
        "prior_runs": n_prior,
        "multiplicity_nag": n_prior >= get("multiplicity_nag_after", 10),
        "code": emit_code(entry, spec, params),
        "params": params,
        "project_id": project_id,
    }


# ─────────────────────────────────────────────────────────────────────────
#  Code emission. Reviewer-facing snippets for the resolved analysis. The
#  immutable run JSON/specification is the canonical reproduction record; a
#  snippet may still need the corresponding data-preparation variables.
# ─────────────────────────────────────────────────────────────────────────

CODE_PY = {
    "ttest_ind": "res = stats.ttest_ind(a, b, equal_var={welch_not})",
    "ttest_paired": "res = stats.ttest_rel(a, b)",
    "ttest_1samp": "res = stats.ttest_1samp(x, popmean={mu})",
    "mannwhitney": "res = stats.mannwhitneyu(a, b, alternative='{alternative}')",
    "wilcoxon": "res = stats.wilcoxon(a, b)",
    "anova_oneway": "res = stats.f_oneway(*groups)",
    "welch_anova": "res = pg.welch_anova(data=df, dv='{dv}', between='{group}')",
    "kruskal": "res = stats.kruskal(*groups)",
    "friedman": "res = stats.friedmanchisquare(*conditions)",
    "chi2": "chi2, p, dof, expected = stats.chi2_contingency(table, correction={yates})",
    "fisher": "odds, p = stats.fisher_exact(table, alternative='{alternative}')",
    "correlation": "r, p = stats.{method}r(x, y)",
    "linreg": "model = sm.OLS(y, sm.add_constant(X)).fit()",
    "logreg": "model = sm.Logit(y, sm.add_constant(X)).fit()",
    "roc": "fpr, tpr, thr = roc_curve(truth, score); auc = roc_auc_score(truth, score)",
    "kaplan_meier": "kmf = KaplanMeierFitter().fit(time, event)",
    "poisson_reg": "import statsmodels.api as sm\nimport statsmodels.formula.api as smf\n"
                   "model = smf.glm('{dv} ~ {predictors_plus}', data=df,\n"
                   "                family=sm.families.Poisson()).fit()  # exp(model.params) = IRR",
    "anova_rm": "import pingouin as pg\n"
                "res = pg.rm_anova(df, dv='{dv}', within='{within}', subject='{subject}',\n"
                "                  correction=True, detailed=True)",
    "cox": "from lifelines import CoxPHFitter\n"
           "cph = CoxPHFitter().fit(df, duration_col='{time}', event_col='{event}',\n"
           "                        formula='{predictors_plus}')",
    "ancova": "import statsmodels.api as sm\nimport statsmodels.formula.api as smf\n"
              "model = smf.ols('{dv} ~ C({group}) + {covariates_plus}', data=df).fit()\n"
              "sm.stats.anova_lm(model, typ=2)",
}

CODE_R = {
    "ttest_ind": 't.test({dv} ~ {group}, data = d, var.equal = {r_var_equal})',
    "ttest_paired": 't.test(d${a}, d${b}, paired = TRUE)',
    "mannwhitney": 'wilcox.test({dv} ~ {group}, data = d)',
    "anova_oneway": 'summary(aov({dv} ~ {group}, data = d))',
    "kruskal": 'kruskal.test({dv} ~ {group}, data = d)',
    "chi2": 'chisq.test(table(d${row}, d${col}))',
    "fisher": 'fisher.test(table(d${row}, d${col}))',
    "correlation": 'cor.test(d${x}, d${y}, method = "{method}")',
    "linreg": 'summary(lm({dv} ~ ., data = d))',
    "logreg": 'summary(glm({dv} ~ ., data = d, family = binomial))',
    "meta_effect": 'metafor::rma(yi = effect, sei = se, method = "{tau_method}")',
    "kaplan_meier": 'survfit(Surv({time}, {event}) ~ {group}, data = d)',
    "poisson_reg": 'summary(glm({dv} ~ {predictors_plus}, data = d, family = poisson))  # exp(coef) = IRR',
    "anova_rm": 'summary(aov({dv} ~ {within} + Error({subject}/{within}), data = d))',
    "cox": 'coxph(Surv({time}, {event}) ~ {predictors_plus}, data = d, ties = "efron")',
    "ancova": 'car::Anova(lm({dv} ~ {group} + {covariates_plus}, data = d), type = 2)',
}


def emit_code(entry, spec, params):
    roles = {k: (v if isinstance(v, str) else (v[0] if v else ""))
             for k, v in (spec.get("roles") or {}).items()}
    fill = dict(params or {})
    fill.update(roles)
    fill["welch_not"] = "False" if params.get("welch", True) else "True"
    fill["r_var_equal"] = "FALSE" if params.get("welch", True) else "TRUE"
    fill["yates"] = str(bool(params.get("yates", True)))
    fill.setdefault("alternative", "two-sided")
    fill.setdefault("method", "pearson")
    for key in ("covariates", "predictors"):
        cols = (spec.get("roles") or {}).get(key) or []
        fill[f"{key}_plus"] = " + ".join([cols] if isinstance(cols, str) else cols)

    def safe(tpl):
        try:
            return tpl.format(**{k: v for k, v in fill.items() if v is not None})
        except (KeyError, IndexError, ValueError):
            return tpl

    py = CODE_PY.get(entry["id"])
    r = CODE_R.get(entry["id"])
    header_py = (
        "import pandas as pd\n"
        "from scipy import stats\n"
        f"df = pd.read_csv('data.csv')\n"
        f"# seed {get('seed')}, alpha {get('alpha')}\n"
    )
    return {
        "python": (header_py + safe(py)) if py else
                  f"# No emitted snippet for {entry['id']} yet.",
        "r": safe(r) if r else f"# No emitted snippet for {entry['id']} yet.",
    }
_RUNNERS = None


def runners():
    global _RUNNERS
    if _RUNNERS is None:
        from .runners import RUNNERS
        _RUNNERS = RUNNERS
    return _RUNNERS


def versions():
    import sys
    out = {"python": sys.version.split()[0]}
    for m in ("numpy", "pandas", "scipy", "statsmodels", "pingouin", "lifelines",
              "sklearn", "matplotlib"):
        try:
            import importlib
            out[m] = getattr(importlib.import_module(m), "__version__", "?")
        except Exception:
            pass
    return out


def run(spec, ctl=None):
    t0 = time.time()
    requested_entry = REGISTRY.get(spec.get("test"))
    if not requested_entry:
        raise ValueError(f"Unknown test {spec.get('test')!r}.")

    pre = preflight(spec)
    if pre["errors"]:
        return {"ok": False, "errors": pre["errors"], "checks": pre["checks"]}

    try:
        df, roles, m, project_id = _dataset_context(spec)
    except Exception as exc:
        return {"ok": False, "errors": [str(exc)], "checks": pre.get("checks", [])}

    entry = requested_entry
    used_test = entry["id"]
    note = None
    if pre["action"].startswith("fallback:") and entry.get("fallback"):
        used_test = entry["fallback"]
        note = (f"Assumption failure switched this to {REGISTRY[used_test]['label']} "
                f"automatically ({pre['message']}).")
        entry = REGISTRY[used_test]
    elif not pre["ok"]:
        db.log_run(project_id=project_id, dataset_id=spec.get("dataset"),
                   dataset_sha=m["sha256"] if m else None,
                   dictionary_sha=m.get("dictionary_sha") if m else None,
                   test_id=entry["id"], spec=spec, assumptions=pre["checks"],
                   status="blocked", error=pre["message"], seed=get("seed"), alpha=get("alpha"), ci_level=get("ci_level"),
                   versions=versions(), duration_ms=0)
        return {"ok": False, "blocked": True, "errors": [pre["message"]],
                "checks": pre["checks"],
                "fallback": entry.get("fallback")}

    errors, params = validate_spec(entry, spec, df=df,
                                   dictionary=(m or {}).get("dictionary"))
    if errors:
        # A fallback can have a stricter contract than the requested method.
        db.log_run(project_id=project_id, dataset_id=spec.get("dataset"),
                   dataset_sha=m["sha256"] if m else None,
                   dictionary_sha=m.get("dictionary_sha") if m else None,
                   test_id=used_test, spec=spec, assumptions=pre["checks"],
                   status="blocked", error="; ".join(errors), seed=get("seed"), alpha=get("alpha"), ci_level=get("ci_level"),
                   versions=versions(), duration_ms=int((time.time() - t0) * 1000),
                   note=note)
        return {"ok": False, "blocked": True, "errors": errors,
                "checks": pre["checks"]}

    final_code = emit_code(entry, spec, params)

    fn = runners().get(used_test)
    if fn is None:
        msg = (f"{entry['label']} is declared but its runner is not written yet.\n"
               f"Add to labdesk/runners/: def {used_test}(df, roles, params, ctl) -> dict")
        db.log_run(project_id=project_id, dataset_id=spec.get("dataset"),
                   dataset_sha=m["sha256"] if m else None,
                   dictionary_sha=m.get("dictionary_sha") if m else None,
                   test_id=used_test, spec=spec, assumptions=pre["checks"],
                   status="failed", error=msg, seed=get("seed"), alpha=get("alpha"), ci_level=get("ci_level"), versions=versions(),
                   duration_ms=int((time.time() - t0) * 1000), note=note,
                   code_python=final_code["python"], code_r=final_code["r"])
        raise NotImplementedRunner(msg)

    # Runtime context is deliberately injected only after validation/code
    # emission. Runners that need ledger/workspace context can consume these
    # private keys without making them part of the user's statistical spec.
    runtime_params = dict(params)
    runtime_params["_project_id"] = project_id
    runtime_params["_dataset_sha"] = m.get("sha256") if m else None
    try:
        result = fn(df, roles, runtime_params, ctl)
    except Exception as exc:
        db.log_run(project_id=project_id, dataset_id=spec.get("dataset"),
                   dataset_sha=m["sha256"] if m else None,
                   dictionary_sha=m.get("dictionary_sha") if m else None,
                   test_id=used_test, spec=spec, assumptions=pre["checks"],
                   status="failed", error=f"{type(exc).__name__}: {exc}",
                   seed=get("seed"), alpha=get("alpha"), ci_level=get("ci_level"), versions=versions(),
                   duration_ms=int((time.time() - t0) * 1000), note=note,
                   code_python=final_code["python"], code_r=final_code["r"])
        raise
    result.setdefault("test", entry["label"])
    result.setdefault("test_id", used_test)
    if note:
        result["note"] = note

    run_id = db.log_run(
        project_id=project_id, dataset_id=spec.get("dataset"),
        dataset_sha=m["sha256"] if m else None,
        dictionary_sha=m.get("dictionary_sha") if m else None,
        test_id=used_test, spec=spec, assumptions=pre["checks"],
        result=result, code_python=final_code["python"], code_r=final_code["r"],
        seed=get("seed"), alpha=get("alpha"), ci_level=get("ci_level"), versions=versions(), status="ok",
        duration_ms=int((time.time() - t0) * 1000), note=note,
    )
    result["run_id"] = run_id
    result["project_id"] = project_id
    result["checks"] = pre["checks"]
    result["code"] = final_code
    result["prior_runs"] = pre["prior_runs"]
    result["multiplicity_nag"] = pre["multiplicity_nag"]
    result["ok"] = True
    return result
