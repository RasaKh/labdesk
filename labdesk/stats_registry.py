"""
TEST_REGISTRY.

Pure data. The statistics pane, the variable pickers, the assumption strip,
the effect-size menu and the suggested plots are all generated from these
entries. Adding a test means adding one dict here plus one function in
stats_run.RUNNERS.

status:
  ready   runner implemented and exercised
  stub    declared, wired into the UI, runner raises NotImplemented with the
          exact signature to fill in. This is deliberate: the shape of the
          tool is complete even where the arithmetic is not.
"""

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
    # ── Three or more groups ─────────────────────────────────────────────
    T("anova_oneway", "One-way ANOVA", "Three or more groups", status=READY,
      blurb="Compares means across three or more independent groups.",
      roles=[R("dv", "Outcome", "continuous"), R("group", "Factor", "categorical", levels=[3, 1000000])],
      params=[P("welch", "Welch correction", "bool", default=False,
                help="Switch on when Levene fails; it is the recommended default in "
                     "unbalanced designs."),
              P("posthoc", "Post-hoc test", "select", default="tukey",
                choices=[("none", "None"), ("tukey", "Tukey HSD"), ("games_howell", "Games-Howell"),
                         ("bonferroni", "Pairwise t with Bonferroni"), ("holm", "Pairwise t with Holm"),
                         ("dunnett", "Dunnett vs control")]),
              P("control", "Control level (Dunnett)", "text",
                depends={"param": "posthoc", "equals": "dunnett"})],
      assumptions=["three_plus_levels", "group_sizes", "normality_by_group",
                   "homogeneity", "independence"],
      effects=["eta_squared", "partial_eta_squared", "omega_squared"],
      plots=["bar_sig", "box", "raincloud", "means_ci"],
      fallback="kruskal"),

    T("anova_factorial", "Factorial ANOVA", "Three or more groups", status=READY,
      blurb="Two or more crossed factors with interaction terms.",
      roles=[R("dv", "Outcome", "continuous"), R("factors", "Factors", "categorical", 2, 4)],
      params=[P("interactions", "Include interactions", "bool", default=True),
              P("ss_type", "Sum of squares", "select", default="2",
                choices=[("1", "Type I"), ("2", "Type II"), ("3", "Type III")],
                help="Type II is the sensible default for unbalanced designs without "
                     "a significant interaction; Type III when the interaction matters."),
              P("posthoc", "Post-hoc test", "select", default="tukey",
                choices=["none", "tukey", "holm", "bonferroni"])],
      assumptions=["group_sizes", "normality_by_group", "homogeneity", "independence"],
      effects=["partial_eta_squared", "omega_squared"],
      plots=["interaction", "bar_sig", "means_ci"], deps=["scipy", "statsmodels"]),

    T("ancova", "ANCOVA", "Three or more groups", status=READY,
      blurb="Group comparison adjusted for one or more continuous covariates.",
      roles=[R("dv", "Outcome", "continuous"), R("group", "Factor", "categorical"),
             R("covariates", "Covariates", "continuous", 1, 6)],
      params=[P("homog_slopes", "Test homogeneity of regression slopes", "bool", default=True),
              P("emmeans", "Report estimated marginal means", "bool", default=True,
                help="Group means predicted at the covariates' overall means."),
              CI],
      assumptions=["normality_by_group", "homogeneity", "linearity", "independence"],
      effects=["partial_eta_squared"], plots=["means_ci"],
      deps=["scipy", "statsmodels"]),

    T("anova_rm", "Repeated-measures ANOVA", "Three or more groups", status=READY,
      blurb="Within-subject factor across three or more time points or conditions. "
            "Subjects missing any condition are excluded.",
      roles=[R("dv", "Outcome", "continuous"), R("subject", "Subject id", "id"),
             R("within", "Within-subject factor", "categorical")],
      params=[P("correction", "Sphericity correction", "select", default="auto",
                choices=[("none", "None"), ("gg", "Greenhouse-Geisser"),
                         ("hf", "Huynh-Feldt"), ("auto", "Automatic (GG if Mauchly fails)")]),
              P("posthoc", "Post-hoc", "select", default="holm",
                choices=["none", "holm", "bonferroni"])],
      assumptions=["sphericity"],
      effects=["partial_eta_squared", "generalized_eta_squared"],
      plots=["means_ci", "bar_sig"], deps=["scipy", "pingouin"],
      fallback="friedman"),

    T("anova_mixed", "Mixed ANOVA", "Three or more groups",
      blurb="One between-subject factor and one within-subject factor.",
      roles=[R("dv", "Outcome", "continuous"), R("subject", "Subject id", "id"),
             R("within", "Within factor", "categorical"), R("between", "Between factor", "categorical")],
      params=[P("correction", "Sphericity correction", "select", default="auto",
                choices=["none", "gg", "hf", "auto"])],
      assumptions=["sphericity", "normality_by_group", "homogeneity"],
      effects=["partial_eta_squared"], plots=["interaction", "spaghetti"],
      deps=["scipy", "pingouin"]),

    T("manova", "MANOVA", "Three or more groups",
      blurb="Several correlated outcomes tested jointly.",
      roles=[R("dvs", "Outcomes", "continuous", 2, 10), R("group", "Factor", "categorical")],
      params=[P("statistic", "Test statistic", "select", default="pillai",
                choices=[("pillai", "Pillai's trace"), ("wilks", "Wilks' lambda"),
                         ("hotelling", "Hotelling-Lawley"), ("roy", "Roy's largest root")])],
      effects=["partial_eta_squared"], deps=["scipy", "statsmodels"]),

    T("kruskal", "Kruskal-Wallis", "Three or more groups", status=READY,
      blurb="Rank-based omnibus test across three or more independent groups.",
      roles=[R("dv", "Outcome", "continuous"), R("group", "Factor", "categorical", levels=[3, 1000000])],
      params=[P("posthoc", "Post-hoc", "select", default="dunn",
                choices=[("none", "None"), ("dunn", "Dunn")]),
              CORRECTION],
      assumptions=["three_plus_levels", "group_sizes", "independence"],
      effects=["epsilon_squared", "eta_squared_h"],
      plots=["box", "raincloud", "bar_sig"]),

    T("friedman", "Friedman test", "Three or more groups", status=READY,
      blurb="Rank-based repeated measures across three or more conditions.",
      roles=[R("dv", "Outcome", "continuous"), R("subject", "Subject id", "id"),
             R("within", "Condition", "categorical", levels=[3, 1000000])],
      params=[P("posthoc", "Post-hoc", "select", default="wilcoxon_holm",
                choices=[("none", "None"),
                         ("wilcoxon_holm", "Pairwise Wilcoxon with Holm correction")])],
      effects=["kendalls_w"], plots=["spaghetti", "box"]),

    T("art_anova", "Aligned rank transform ANOVA", "Three or more groups",
      blurb="Nonparametric factorial designs including interactions, which "
            "rank tests otherwise cannot handle.",
      roles=[R("dv", "Outcome", "continuous"), R("factors", "Factors", "categorical", 1, 3)],
      params=[], deps=["scipy", "statsmodels"], plots=["interaction"]),

    T("welch_anova", "Welch's ANOVA", "Three or more groups", status=READY,
      blurb="Omnibus comparison that does not assume equal variances.",
      roles=[R("dv", "Outcome", "continuous"), R("group", "Factor", "categorical", levels=[3, 1000000])],
      params=[P("posthoc", "Post-hoc", "select", default="games_howell",
                choices=["none", "games_howell", "holm"])],
      effects=["omega_squared"], plots=["bar_sig", "box"]),

    # ── Post hoc and multiplicity ────────────────────────────────────────
    T("pairwise", "Pairwise comparisons", "Post hoc and multiplicity", status=READY,
      blurb="All pairs, or all against a control, with a chosen correction.",
      roles=[R("dv", "Outcome", "continuous"), R("group", "Factor", "categorical")],
      params=[P("test", "Test", "select", default="t",
                choices=[("t", "t-test"), ("welch", "Welch t"), ("mwu", "Mann-Whitney"),
                         ("tukey", "Tukey HSD"), ("games_howell", "Games-Howell"),
                         ("dunn", "Dunn")]),
              CORRECTION,
              P("against", "Compare", "select", default="all",
                choices=[("all", "All pairs"), ("control", "All against a control")]),
              P("control", "Control level", "text", depends={"param": "against", "equals": "control"})],
      effects=["hedges_g", "mean_diff_ci"], plots=["bar_sig"]),

    T("padjust", "Adjust a set of p values", "Post hoc and multiplicity", status=READY,
      blurb="Paste or select a column of p values and apply a correction. "
            "Useful for adjusting across outcomes rather than within one test.",
      roles=[R("pvals", "p value column", "continuous", 0, 1, optional=True)],
      params=[P("paste", "Or paste p values", "textarea",
                placeholder="0.001, 0.04, 0.22, 0.51"),
              CORRECTION,
              P("alpha", "Alpha", "number", default=0.05)],
      plots=["pvalue_hist"]),

    T("multiplicity_audit", "Multiplicity audit", "Post hoc and multiplicity", status=READY,
      blurb="Every test run against the current dataset, with the family-wise error "
            "rate that implies. The provenance ledger makes this possible; it is the "
            "honest counterpart to how cheap running one more test has become.",
      roles=[], params=[P("alpha", "Nominal alpha", "number", default=0.05)]),
    # ── Categorical and proportions ──────────────────────────────────────
    T("chi2", "Chi-square test", "Categorical and proportions", status=READY,
      blurb="Association between two categorical variables.",
      roles=[R("row", "Variable 1", "categorical"), R("col", "Variable 2", "categorical")],
      params=[P("yates", "Yates continuity correction (2x2)", "bool", default=True),
              P("residuals", "Report standardised residuals", "bool", default=True)],
      assumptions=["expected_counts", "independence"],
      effects=["cramers_v", "phi", "odds_ratio", "risk_ratio"],
      plots=["stacked_bar", "mosaic"], fallback="fisher"),

    T("fisher", "Fisher's exact test", "Categorical and proportions", status=READY,
      blurb="Exact test for sparse tables. Extends beyond 2x2 with the "
            "Freeman-Halton computation.",
      roles=[R("row", "Variable 1", "categorical"), R("col", "Variable 2", "categorical")],
      params=[ALT], effects=["odds_ratio", "risk_ratio", "risk_difference"],
      plots=["stacked_bar"]),

    T("mcnemar", "McNemar's test", "Categorical and proportions", status=READY,
      blurb="Paired binary outcomes, for example before and after in the same patients.",
      roles=[R("a", "Before", "binary"), R("b", "After", "binary")],
      params=[P("exact", "Exact binomial", "bool", default=True)],
      effects=["odds_ratio_paired"], plots=[]),

    T("cochran_q", "Cochran's Q", "Categorical and proportions", status=READY,
      blurb="Binary outcome across three or more matched conditions.",
      roles=[R("vars", "Conditions", "binary", 3, 12)],
      params=[P("posthoc", "Post-hoc McNemar", "bool", default=True), CORRECTION]),

    T("armitage", "Cochran-Armitage trend test", "Categorical and proportions", status=READY,
      blurb="Tests for a dose-response trend in proportions across ordered categories.",
      roles=[R("outcome", "Binary outcome", "binary"), R("ordered", "Ordered exposure", "ordinal")],
      params=[ALT], plots=[]),

    T("prop_test", "Proportions and their contrast", "Categorical and proportions", status=READY,
      blurb="Risk ratio, odds ratio, risk difference and number needed to treat, "
            "with confidence intervals.",
      roles=[R("outcome", "Outcome", "binary"), R("group", "Group", "categorical", levels=2)],
      params=[CI, P("measures", "Report", "multiselect",
                    default=["rr", "or", "rd", "nnt"],
                    choices=[("rr", "Risk ratio"), ("or", "Odds ratio"),
                             ("rd", "Risk difference"), ("nnt", "Number needed to treat")]),
              P("ci_method", "Interval method", "select", default="wilson",
                choices=[("wilson", "Wilson"), ("wald", "Wald"), ("agresti", "Agresti-Coull"),
                         ("exact", "Clopper-Pearson exact")], adv=True)],
      plots=["forest_effect", "stacked_bar"]),

    T("binomial", "One-sample proportion", "Categorical and proportions", status=READY,
      roles=[R("outcome", "Binary variable", "binary")],
      params=[P("p0", "Reference proportion", "number", default=0.5, min=0, max=1), ALT, CI]),

    T("goodness_fit", "Goodness of fit", "Categorical and proportions", status=READY,
      blurb="Observed counts against expected proportions.",
      roles=[R("var", "Variable", "categorical")],
      params=[P("expected", "Expected proportions", "text",
                placeholder="Blank for equal, or 0.25,0.25,0.5")]),

    # ── Correlation and agreement ────────────────────────────────────────
    T("correlation", "Correlation", "Correlation and agreement", status=READY,
      blurb="Pearson, Spearman or Kendall, pairwise or as a matrix.",
      roles=[R("vars", "Variables", "continuous", 2, 40)],
      params=[P("method", "Coefficient", "select", default="pearson",
                choices=[("pearson", "Pearson"), ("spearman", "Spearman"),
                         ("kendall", "Kendall tau-b")]),
              CI, CORRECTION,
              P("partial", "Control for", "columns", adv=True,
                help="Produces partial correlations holding these constant.")],
      assumptions=["linearity", "independence"],
      effects=["r", "r_squared", "fisher_z_ci"],
      plots=["scatter_fit", "corr_matrix", "pair_grid"]),

    T("icc", "Intraclass correlation", "Correlation and agreement", status=READY,
      blurb="All six forms. The form matters: reporting ICC without specifying "
            "which one is the most common reliability reporting error.",
      roles=[R("subject", "Subject id", "id"), R("rater", "Rater or method", "categorical"),
             R("value", "Measurement", "continuous")],
      params=[P("form", "Form", "select", default="ICC2k",
                choices=[("ICC1", "ICC(1): one-way random, single"),
                         ("ICC2", "ICC(2,1): two-way random, single, absolute"),
                         ("ICC3", "ICC(3,1): two-way mixed, single, consistency"),
                         ("ICC1k", "ICC(1,k): one-way random, average"),
                         ("ICC2k", "ICC(2,k): two-way random, average, absolute"),
                         ("ICC3k", "ICC(3,k): two-way mixed, average, consistency")]),
              CI],
      plots=["bland_altman", "scatter_fit"], deps=["scipy", "pingouin"]),

    T("bland_altman", "Bland-Altman agreement", "Correlation and agreement", status=READY,
      blurb="Bias and limits of agreement between two methods. The right analysis "
            "when the question is agreement rather than association.",
      roles=[R("a", "Method 1", "continuous"), R("b", "Method 2", "continuous")],
      params=[P("loa", "Limits of agreement", "number", default=1.96, adv=True),
              P("proportional", "Test for proportional bias", "bool", default=True),
              CI],
      plots=["bland_altman"]),

    T("kappa", "Kappa agreement", "Correlation and agreement", status=READY,
      blurb="Cohen's kappa for two raters, Fleiss for more, weighted for ordinal scales. "
            "Also used for the screening reliability check in evidence synthesis.",
      roles=[R("raters", "Rater columns", "any", 2, 20)],
      params=[P("weights", "Weighting", "select", default="none",
                choices=[("none", "Unweighted"), ("linear", "Linear"), ("quadratic", "Quadratic")]),
              CI],
      plots=[]),

    T("cronbach", "Internal consistency", "Correlation and agreement", status=READY,
      blurb="Cronbach's alpha with item-total statistics and alpha-if-item-dropped.",
      roles=[R("items", "Items", "continuous", 3, 100)],
      params=[P("drop_stats", "Alpha if item dropped", "bool", default=True), CI]),

    T("passing_bablok", "Passing-Bablok regression", "Correlation and agreement",
      blurb="Method-comparison regression robust to error in both variables.",
      roles=[R("a", "Reference method", "continuous"), R("b", "Test method", "continuous")],
      params=[CI], plots=["method_compare"]),

    T("deming", "Deming regression", "Correlation and agreement",
      roles=[R("a", "Reference method", "continuous"), R("b", "Test method", "continuous")],
      params=[P("lambda", "Error variance ratio", "number", default=1.0), CI],
      plots=["method_compare"]),
    # ── Regression ───────────────────────────────────────────────────────
    T("linreg", "Linear regression", "Regression", status=READY,
      blurb="Ordinary least squares with full diagnostics.",
      roles=[R("dv", "Outcome", "continuous"), R("predictors", "Predictors", "any", 1, 30)],
      params=[P("standardise", "Standardised coefficients", "bool", default=False),
              P("robust_se", "Robust standard errors", "select", default="none",
                choices=[("none", "Classical"), ("HC0", "HC0"), ("HC1", "HC1"),
                         ("HC3", "HC3 (recommended)")]),
              CI],
      assumptions=["linearity", "homoscedasticity", "vif", "independence"],
      effects=["r_squared", "adj_r_squared", "beta_ci", "cohen_f2"],
      plots=["scatter_fit", "residual_plots", "coef_forest"]),

    T("logreg", "Logistic regression", "Regression", status=READY,
      blurb="Binary outcome, reported as odds ratios with intervals.",
      roles=[R("dv", "Binary outcome", "binary"), R("predictors", "Predictors", "any", 1, 30)],
      params=[P("ref_level", "Outcome reference level", "text"),
              P("penalty", "Penalty", "select", default="none",
                choices=[("none", "None"), ("firth", "Firth (separation)"),
                         ("l2", "Ridge"), ("l1", "Lasso")]),
              P("report", "Report", "select", default="or",
                choices=[("or", "Odds ratios"), ("beta", "Log-odds coefficients")]),
              CI],
      assumptions=["epv", "vif", "independence"],
      effects=["odds_ratio", "auc", "pseudo_r2"],
      plots=["coef_forest", "roc", "calibration"], deps=["scipy", "sklearn"]),

    T("ordinal_reg", "Ordinal logistic regression", "Regression",
      blurb="Proportional-odds model for ordered outcomes.",
      roles=[R("dv", "Ordered outcome", "ordinal"), R("predictors", "Predictors", "any", 1, 30)],
      params=[P("test_po", "Test the proportional odds assumption", "bool", default=True), CI],
      deps=["scipy", "statsmodels"], plots=["coef_forest"]),

    T("multinom_reg", "Multinomial logistic regression", "Regression",
      roles=[R("dv", "Nominal outcome", "categorical"), R("predictors", "Predictors", "any", 1, 30)],
      params=[P("ref_level", "Reference category", "text"), CI],
      deps=["scipy", "statsmodels"], plots=["coef_forest"]),

    T("poisson_reg", "Poisson and negative binomial", "Regression", status=READY,
      blurb="Count outcomes, with an overdispersion check that decides between them. "
            "Coefficients are incidence rate ratios.",
      roles=[R("dv", "Count outcome", "continuous"), R("predictors", "Predictors", "any", 1, 30),
             R("offset", "Exposure (person-time)", "continuous", 0, 1, optional=True)],
      params=[P("family", "Family", "select", default="auto",
                choices=[("auto", "Automatic on overdispersion"), ("poisson", "Poisson"),
                         ("negbin", "Negative binomial")]),
              CI],
      assumptions=["independence"],
      deps=["scipy", "statsmodels"], effects=["irr"], plots=["coef_forest"]),

    T("quantile_reg", "Quantile regression", "Regression",
      roles=[R("dv", "Outcome", "continuous"), R("predictors", "Predictors", "any", 1, 30)],
      params=[P("q", "Quantile", "number", default=0.5, min=0.01, max=0.99), CI],
      deps=["scipy", "statsmodels"], plots=["quantile_fan"]),

    T("mixed_model", "Linear mixed-effects model", "Regression",
      blurb="Random intercepts and slopes for clustered or repeated data. "
            "The correct answer whenever subjects contribute more than one row.",
      roles=[R("dv", "Outcome", "continuous"), R("fixed", "Fixed effects", "any", 1, 30),
             R("group", "Grouping (random intercept)", "id"),
             R("random_slope", "Random slope on", "any", 0, 3, optional=True)],
      params=[P("reml", "REML", "bool", default=True),
              P("icc", "Report ICC", "bool", default=True), CI],
      deps=["scipy", "statsmodels"], plots=["spaghetti", "coef_forest", "caterpillar"]),

    T("gee", "Generalised estimating equations", "Regression",
      roles=[R("dv", "Outcome", "any"), R("predictors", "Predictors", "any", 1, 30),
             R("group", "Cluster id", "id")],
      params=[P("family", "Family", "select", default="gaussian",
                choices=["gaussian", "binomial", "poisson"]),
              P("corr", "Working correlation", "select", default="exchangeable",
                choices=["independence", "exchangeable", "ar1", "unstructured"]), CI],
      deps=["scipy", "statsmodels"], plots=["coef_forest"]),

    T("penalised_reg", "Penalised regression", "Regression",
      blurb="Lasso, ridge or elastic net with cross-validated lambda.",
      roles=[R("dv", "Outcome", "any"), R("predictors", "Predictors", "any", 2, 500)],
      params=[P("kind", "Penalty", "select", default="lasso",
                choices=["lasso", "ridge", "elasticnet"]),
              P("l1_ratio", "L1 ratio", "number", default=0.5, min=0, max=1,
                depends={"param": "kind", "equals": "elasticnet"}),
              P("cv", "Cross-validation folds", "int", default=10, min=3, max=50)],
      deps=["sklearn"], plots=["coef_path", "cv_curve"]),

    T("model_compare", "Model comparison", "Regression",
      blurb="Nested likelihood-ratio tests, AIC, BIC and adjusted R².",
      roles=[], params=[P("runs", "Runs to compare", "multiselect")],
      deps=["scipy", "statsmodels"]),

    # ── Survival ─────────────────────────────────────────────────────────
    T("kaplan_meier", "Kaplan-Meier", "Survival", status=READY,
      blurb="Survival curves with a number-at-risk table and median survival.",
      roles=[R("time", "Time to event", "continuous"), R("event", "Event indicator", "binary"),
             R("group", "Group", "categorical", 0, 1, optional=True)],
      params=[P("event_level", "Event level", "text",
                help="Which observed value means the event occurred. Usually inferred automatically for 0/1, yes/no, event/censored, etc."),
              P("logrank", "Log-rank test", "bool", default=True),
              P("at_risk", "Number-at-risk table", "bool", default=True),
              P("landmarks", "Report survival at times", "text", placeholder="12, 24, 60"),
              CI],
      effects=["median_survival", "hazard_ratio", "rmst"],
      plots=["km_curve"]),

    T("cox", "Cox proportional hazards", "Survival", status=READY,
      blurb="Hazard ratios adjusted for covariates, with a Schoenfeld-residual test of "
            "proportional hazards. Ties are handled by Efron's method.",
      roles=[R("time", "Time to event", "continuous"), R("event", "Event indicator", "binary"),
             R("predictors", "Covariates", "any", 1, 30),
             R("strata", "Stratify by", "categorical", 0, 2, optional=True)],
      params=[P("event_level", "Event level", "text",
                help="Which observed value means the event occurred. Usually inferred automatically for 0/1, yes/no, event/censored, etc."),
              P("check_ph", "Test proportional hazards", "bool", default=True),
              CI],
      assumptions=["proportional_hazards", "epv"],
      effects=["hazard_ratio", "concordance"],
      plots=["coef_forest"], deps=["lifelines"]),

    T("competing_risks", "Competing risks", "Survival",
      blurb="Cumulative incidence functions and Fine-Gray subdistribution hazards. "
            "Kaplan-Meier overestimates risk when competing events are common.",
      roles=[R("time", "Time", "continuous"), R("event", "Event type", "categorical"),
             R("predictors", "Covariates", "any", 0, 20, optional=True)],
      params=[P("event_of_interest", "Event of interest", "text"), CI],
      plots=["cumulative_incidence", "coef_forest"], deps=["lifelines"]),

    T("rmst", "Restricted mean survival time", "Survival",
      blurb="Difference in area under the survival curve up to a horizon. "
            "Interpretable in months of life and free of the PH assumption.",
      roles=[R("time", "Time", "continuous"), R("event", "Event", "binary"),
             R("group", "Group", "categorical")],
      params=[P("tau", "Horizon (tau)", "number"), CI],
      plots=["km_curve", "rmst_area"], deps=["lifelines"]),

    T("parametric_survival", "Parametric survival (AFT)", "Survival",
      roles=[R("time", "Time", "continuous"), R("event", "Event", "binary"),
             R("predictors", "Covariates", "any", 1, 20)],
      params=[P("dist", "Distribution", "select", default="weibull",
                choices=["exponential", "weibull", "lognormal", "loglogistic"]), CI],
      deps=["lifelines"], plots=["km_curve", "coef_forest"]),
]


REGISTRY = index(TESTS)
GROUPS = group_registry(TESTS)


def get(test_id):
    return REGISTRY.get(test_id)


def ready_count():
    return sum(1 for t in TESTS if t["status"] == READY)
