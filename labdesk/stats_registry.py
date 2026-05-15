from .schema import P, R, group_registry, index

READY, STUB = "ready", "stub"


def T(id, label, group, blurb="", roles=None, params=None, assumptions=None,
      effects=None, plots=None, fallback=None, deps=None, status=STUB,
      reports=None, cite=None):
    return {
        "id": id, "label": label, "group": group, "blurb": blurb,
        "roles": roles or [], "params": params or [],
        "assumptions": assumptions or [], "effects": effects or [],
        "plots": plots or [], "fallback": fallback,
        "deps": deps or ["scipy"], "status": status,
        "reports": reports or [], "cite": cite,
    }


# Shared parameter blocks
ALT = P("alternative", "Alternative hypothesis", "select",
        default="two-sided",
        choices=[("two-sided", "Two-sided"), ("greater", "Greater"), ("less", "Less")],
        help="One-sided tests must be justified before seeing the data.")
CI = P("ci", "Confidence level", "number", default=0.95, min=0.5, max=0.9999, step=0.01)
CORRECTION = P("correction", "Multiplicity correction", "select", default="holm",
               choices=[("none", "None"), ("bonferroni", "Bonferroni"), ("holm", "Holm"),
                        ("sidak", "Šidák"), ("fdr_bh", "Benjamini-Hochberg (FDR)"),
                        ("fdr_by", "Benjamini-Yekutieli"), ("storey", "Storey q-value")])
BOOT = P("bootstrap", "Bootstrap resamples for the CI", "int", default=0, min=0, max=100000,
         adv=True, help="0 uses the analytic interval. 2000 is a reasonable floor when used.")


TESTS = [

    # ── Descriptives ─────────────────────────────────────────────────────
    T("describe", "Descriptive summary", "Descriptives", status=READY,
      blurb="n, missing, central tendency, spread and shape for every selected variable.",
      roles=[R("vars", "Variables", "any", 1, 50)],
      params=[P("by", "Split by", "column", help="Optional grouping variable."),
              P("robust", "Include median, IQR and MAD", "bool", default=True),
              P("normality", "Flag non-normal variables", "bool", default=True)],
      plots=["hist", "box", "raincloud"]),

    T("table1", "Table 1: baseline characteristics", "Descriptives", status=READY,
      blurb="Publication-ready baseline table. Picks the right test per variable type "
            "and reports standardised mean differences alongside p values.",
      roles=[R("vars", "Characteristics", "any", 1, 60),
             R("group", "Group", "categorical", 0, 1, optional=True)],
      params=[P("show_p", "Include p values", "bool", default=True),
              P("show_smd", "Include standardised mean differences", "bool", default=True,
                help="SMD is the better comparability measure in matched or weighted cohorts, "
                     "where p values are not meaningful."),
              P("nonnormal", "Force median (IQR) for these", "columns"),
              P("cat_test", "Categorical test", "select", default="auto",
                choices=[("auto", "Automatic"), ("chi2", "Chi-square"), ("fisher", "Fisher exact")]),
              P("overall", "Include an overall column", "bool", default=True),
              P("digits", "Decimal places", "int", default=1, min=0, max=4)],
      reports=["table1_docx", "table1_html"]),

    T("freq", "Frequency table", "Descriptives", status=READY,
      blurb="Counts, percentages and cumulative percentages, with missing shown separately.",
      roles=[R("vars", "Variables", "any", 1, 20)],
      params=[P("sort", "Sort", "select", default="count",
                choices=[("count", "By count"), ("label", "By label")]),
              P("drop_missing", "Exclude missing from percentages", "bool", default=False)]),

    T("crosstab", "Cross-tabulation", "Descriptives", status=READY,
      blurb="Contingency table with row, column or total percentages.",
      roles=[R("row", "Rows", "categorical"), R("col", "Columns", "categorical")],
      params=[P("pct", "Percentages", "select", default="col",
                choices=[("none", "None"), ("row", "By row"), ("col", "By column"), ("total", "Of total")]),
              P("residuals", "Show standardised residuals", "bool", default=False)],
      plots=["mosaic", "stacked_bar"]),

    # ── Assumption checks ────────────────────────────────────────────────
    T("normality_check", "Normality", "Assumption checks", status=READY,
      blurb="Shapiro-Wilk, skewness and kurtosis, with a Q-Q plot. Read the plot, "
            "not the p value, once n is above a few hundred.",
      roles=[R("vars", "Variables", "continuous", 1, 20),
             R("group", "Within each level of", "categorical", 0, 1, optional=True)],
      params=[P("method", "Test", "select", default="shapiro",
                choices=[("shapiro", "Shapiro-Wilk"), ("dagostino", "D'Agostino K²"),
                         ("anderson", "Anderson-Darling")])],
      plots=["qq", "hist"]),

    T("variance_check", "Equality of variances", "Assumption checks", status=READY,
      blurb="Levene, Bartlett or Brown-Forsythe across groups.",
      roles=[R("dv", "Outcome", "continuous"), R("group", "Group", "categorical")],
      params=[P("method", "Test", "select", default="levene",
                choices=[("levene", "Levene (median-centred)"), ("bartlett", "Bartlett"),
                         ("brown_forsythe", "Brown-Forsythe"), ("fligner", "Fligner-Killeen")])],
      plots=["box"]),

    T("outlier_check", "Outlier screen", "Assumption checks", status=READY,
      blurb="Flags candidate outliers by several rules at once. Flagging is not deleting; "
            "every exclusion is recorded and appears in the methods text.",
      roles=[R("vars", "Variables", "continuous", 1, 20)],
      params=[P("method", "Rule", "select", default="iqr",
                choices=[("iqr", "Tukey IQR"), ("zscore", "z score"),
                         ("modified_zscore", "Modified z (MAD)"), ("grubbs", "Grubbs"),
                         ("mahalanobis", "Mahalanobis (multivariate)")]),
              P("threshold", "Threshold", "number", help="Blank uses the conventional value.")],
      plots=["box"]),

    T("missing_check", "Missing data pattern", "Assumption checks", status=READY,
      blurb="Per-variable missingness, the pattern table and complete-case count.",
      roles=[R("vars", "Variables", "any", 0, 100, optional=True)],
      params=[], plots=["missing_map"]),

    T("power_achieved", "Achieved power", "Assumption checks", status=READY,
      blurb="Post-hoc power for the observed effect. Reported because reviewers ask, "
            "with the caveat that observed power is a deterministic function of p.",
      roles=[R("dv", "Outcome", "continuous"), R("group", "Group", "categorical")],
      params=[P("alpha", "Alpha", "number", default=0.05, min=0.0001, max=0.5)]),

    # ── Two groups ───────────────────────────────────────────────────────
    T("ttest_ind", "Independent samples t-test", "Two groups", status=READY,
      blurb="Compares means between two independent groups.",
      roles=[R("dv", "Outcome", "continuous"), R("group", "Group", "categorical", levels=2)],
      params=[ALT, CI,
              P("welch", "Welch correction for unequal variances", "bool", default=True,
                help="On by default. It is nearly free when variances are equal and "
                     "correct when they are not.")],
      assumptions=["two_levels", "group_sizes", "normality_by_group", "homogeneity", "independence"],
      effects=["cohen_d", "hedges_g", "glass_delta", "mean_diff_ci"],
      plots=["bar_sig", "box", "raincloud", "violin", "beeswarm"],
      fallback="mannwhitney"),

    T("ttest_paired", "Paired t-test", "Two groups", status=READY,
      blurb="Compares two measurements on the same subjects.",
      roles=[R("a", "Measurement 1", "continuous"), R("b", "Measurement 2", "continuous")],
      params=[ALT, CI],
      assumptions=["pairing", "normality_of_differences"],
      effects=["cohen_dz", "hedges_g", "mean_diff_ci"],
      plots=["paired_lines", "bar_sig", "bland_altman"],
      fallback="wilcoxon"),

    T("ttest_1samp", "One-sample t-test", "Two groups", status=READY,
      blurb="Compares a mean against a reference value.",
      roles=[R("dv", "Variable", "continuous")],
      params=[P("mu", "Reference value", "number", default=0), ALT, CI],
      assumptions=["normality"], effects=["cohen_d", "mean_diff_ci"],
      plots=["hist", "box"], fallback="wilcoxon_1samp"),

    T("mannwhitney", "Mann-Whitney U", "Two groups", status=READY,
      blurb="Rank-based comparison of two independent groups. Tests stochastic "
            "dominance, not medians, unless the distributions have the same shape.",
      roles=[R("dv", "Outcome", "continuous"), R("group", "Group", "categorical", levels=2)],
      params=[ALT, P("continuity", "Continuity correction", "bool", default=True, adv=True),
              P("hl", "Hodges-Lehmann estimate and CI", "bool", default=True)],
      assumptions=["two_levels", "group_sizes", "independence"],
      effects=["rank_biserial", "cles", "hodges_lehmann"],
      plots=["box", "raincloud", "beeswarm", "bar_sig"]),

    T("wilcoxon", "Wilcoxon signed-rank", "Two groups", status=READY,
      blurb="Rank-based paired comparison.",
      roles=[R("a", "Measurement 1", "continuous"), R("b", "Measurement 2", "continuous")],
      params=[ALT, P("zero_method", "Handling of zero differences", "select",
                     default="wilcox", choices=["wilcox", "pratt", "zsplit"], adv=True)],
      assumptions=["pairing"], effects=["rank_biserial", "hodges_lehmann"],
      plots=["paired_lines", "box"]),

    T("wilcoxon_1samp", "One-sample Wilcoxon", "Two groups", status=READY,
      roles=[R("dv", "Variable", "continuous")],
      params=[P("mu", "Reference value", "number", default=0), ALT],
      effects=["rank_biserial"], plots=["hist", "box"]),

    T("permutation_two", "Permutation test", "Two groups", status=READY,
      blurb="Exact null by relabelling. Makes no distributional assumption and "
            "works when n is small enough that asymptotics do not.",
      roles=[R("dv", "Outcome", "continuous"), R("group", "Group", "categorical", levels=2)],
      params=[P("statistic", "Statistic", "select", default="mean_diff",
                choices=[("mean_diff", "Difference in means"),
                         ("median_diff", "Difference in medians"),
                         ("t", "t statistic")]),
              P("n_perm", "Permutations", "int", default=10000, min=100, max=1000000),
              ALT],
      effects=["mean_diff_ci"], plots=["bar_sig", "null_distribution"]),

    T("bootstrap_diff", "Bootstrap difference", "Two groups", status=READY,
      blurb="Percentile and BCa intervals for any two-group contrast.",
      roles=[R("dv", "Outcome", "continuous"), R("group", "Group", "categorical", levels=2)],
      params=[P("statistic", "Statistic", "select", default="mean",
                choices=["mean", "median", "trimmed_mean", "sd", "cv"]),
              P("n_boot", "Resamples", "int", default=5000, min=200, max=200000),
              P("method", "Interval", "select", default="bca",
                choices=[("percentile", "Percentile"), ("bca", "Bias-corrected accelerated")]),
              CI],
      plots=["bootstrap_dist", "bar_sig"]),

    T("brunner_munzel", "Brunner-Munzel", "Two groups", status=READY,
      blurb="Rank test that, unlike Mann-Whitney, does not assume equal shapes.",
      roles=[R("dv", "Outcome", "continuous"), R("group", "Group", "categorical", levels=2)],
      params=[ALT], effects=["cles"], plots=["box", "raincloud"]),
]


REGISTRY = index(TESTS)
GROUPS = group_registry(TESTS)


def get(test_id):
    return REGISTRY.get(test_id)


def ready_count():
    return sum(1 for t in TESTS if t["status"] == READY)