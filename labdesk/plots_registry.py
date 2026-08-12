"""
PLOT_REGISTRY.

Same contract as the test registry. Each plot declares which result kinds it
can render, its own parameters, and whether it is implemented.

Journal export sizing lives here rather than in the renderer because column
widths are an editorial constraint, not a drawing detail: 89 mm single column
and 183 mm double column cover Elsevier, Springer and most society journals.
"""

from .schema import P, group_registry, index

READY, STUB = "ready", "stub"

JOURNAL_PRESETS = [
    ("single_89", "Single column, 89 mm", {"width_mm": 89, "dpi": 300}),
    ("double_183", "Double column, 183 mm", {"width_mm": 183, "dpi": 300}),
    ("nature_single", "Nature single, 89 mm at 600 dpi", {"width_mm": 89, "dpi": 600}),
    ("slide_16_9", "Slide, 16:9", {"width_mm": 254, "dpi": 150}),
    ("poster", "Poster, 200 mm at 600 dpi", {"width_mm": 200, "dpi": 600}),
]

PALETTES = [
    ("okabe_ito", "Okabe-Ito (colourblind safe)"),
    ("viridis", "Viridis"),
    ("grey", "Greyscale"),
    ("hne", "Hematoxylin and eosin"),
    ("nejm", "Journal editorial"),
]


def G(id, label, group, kinds, blurb="", params=None, status=STUB):
    return {"id": id, "label": label, "group": group, "kinds": kinds,
            "blurb": blurb, "params": params or [], "status": status}


# Parameters shared by anything that can carry significance annotation.
SIG_PARAMS = [
    P("annotate", "Significance annotation", "select", default="stars",
      choices=[("none", "None"), ("stars", "Asterisks"), ("p", "Exact p values"),
               ("both", "Asterisks and p values")]),
    P("only_significant", "Only annotate significant comparisons", "bool", default=True,
      help="Off shows ns brackets too, which is honest but crowded."),
    P("bracket_gap", "Gap between stacked brackets", "number", default=0.06, adv=True,
      help="As a fraction of the axis range."),
    P("bracket_tick", "Bracket tick height", "number", default=0.02, adv=True),
    P("star_size", "Annotation size", "number", default=10, adv=True),
]

ERROR_PARAM = P("error", "Error bars", "select", default="ci95",
                choices=[("none", "None"), ("sd", "Standard deviation"),
                         ("sem", "Standard error of the mean"),
                         ("ci95", "95% confidence interval")],
                help="Always state which one in the caption. SEM bars look tighter than "
                     "SD bars and mean something different.")

POINTS_PARAM = P("points", "Overlay individual points", "select", default="jitter",
                 choices=[("none", "None"), ("jitter", "Jittered")],
                 help="Showing the data behind the summary is the single cheapest way to "
                      "make a figure honest.")

COMMON = [
    P("title", "Title", "text"),
    P("xlabel", "x axis label", "text"),
    P("ylabel", "y axis label", "text"),
    P("palette", "Palette", "select", default="okabe_ito", choices=PALETTES),
    P("preset", "Size preset", "select", default="single_89",
      choices=[(p[0], p[1]) for p in JOURNAL_PRESETS]),
    P("format", "Format", "select", default="png",
      choices=[("png", "PNG"), ("pdf", "PDF (vector)"), ("svg", "SVG (vector)"),
               ("tiff", "TIFF"), ("eps", "EPS")]),
    P("dpi", "Resolution", "int", default=300, min=72, max=1200, adv=True),
    P("theme", "Theme", "select", default="publication",
      choices=[("publication", "Publication"), ("dark", "Dark"), ("minimal", "Minimal")]),
    P("grid", "Grid", "select", default="y", choices=[("none", "None"), ("y", "Horizontal"),
                                                      ("both", "Both")], adv=True),
    P("despine", "Remove top and right spines", "bool", default=True, adv=True),
]


PLOTS = [
    # Group comparison
    G("bar_sig", "Bar chart with significance brackets", "Group comparison",
      ["comparison", "anova", "pairwise", "qpcr"], status=READY,
      blurb="Means with error bars, individual points, and auto-stacked significance "
            "brackets that never overlap.",
      params=[ERROR_PARAM, POINTS_PARAM] + SIG_PARAMS + [
          P("bar_width", "Bar width", "number", default=0.6, adv=True),
          P("baseline", "Baseline", "number", default=0, adv=True),
          P("log_y", "Log y axis", "bool", default=False),
          P("hline", "Reference line at", "number", adv=True)]),

    G("box", "Box plot", "Group comparison", ["comparison", "anova", "pairwise"],
      status=READY,
      params=[POINTS_PARAM] + SIG_PARAMS + [
          P("notch", "Notched", "bool", default=False),
          P("whisker", "Whiskers", "select", default="1.5iqr",
            choices=[("1.5iqr", "1.5 × IQR"), ("minmax", "Min to max"),
                     ("p5p95", "5th to 95th percentile")])]),

    G("violin", "Violin plot", "Group comparison", ["comparison", "anova"],
      params=[POINTS_PARAM] + SIG_PARAMS + [
          P("inner", "Inside", "select", default="box",
            choices=[("box", "Box"), ("quartiles", "Quartile lines"), ("none", "Nothing")])]),

    G("raincloud", "Raincloud plot", "Group comparison", ["comparison", "anova"],
      status=READY,
      blurb="Half violin, box and raw points together. Shows the distribution, the "
            "summary and the data in one panel.",
      params=SIG_PARAMS),

    G("beeswarm", "Beeswarm", "Group comparison", ["comparison", "anova"],
      params=SIG_PARAMS + [P("mean_line", "Mean and error bar", "bool", default=True)]),

    G("means_ci", "Means with confidence intervals", "Group comparison",
      ["anova", "comparison", "pairwise"], status=READY,
      params=[ERROR_PARAM, P("connect", "Connect points", "bool", default=False)]),

    G("paired_lines", "Paired before and after", "Group comparison", ["comparison"],
      blurb="One line per subject. Reveals crossover that group means hide.",
      params=SIG_PARAMS + [P("colour_by_direction", "Colour by direction of change",
                             "bool", default=True),
                           P("summary", "Overlay group means", "bool", default=True)]),

    G("spaghetti", "Individual trajectories", "Group comparison", ["anova"],
      params=[P("mean_overlay", "Overlay group mean", "bool", default=True),
              P("alpha", "Line opacity", "number", default=0.3)]),

    G("interaction", "Interaction plot", "Group comparison", ["anova"],
      params=[ERROR_PARAM]),

    G("hist", "Histogram", "Distribution", ["table", "single"], status=READY,
      params=[P("bins", "Bins", "select", default="auto",
                choices=[("auto", "Automatic"), ("fd", "Freedman-Diaconis"),
                         ("sturges", "Sturges"), ("custom", "Custom")]),
              P("n_bins", "Number of bins", "int", default=20,
                depends={"param": "bins", "equals": "custom"}),
              P("density", "Density curve", "bool", default=True),
              P("normal_overlay", "Overlay fitted normal", "bool", default=False)]),

    G("qq", "Q-Q plot", "Distribution", ["table"], status=READY,
      blurb="The plot to read instead of a Shapiro p value once n is large.",
      params=[P("dist", "Reference distribution", "select", default="norm",
                choices=[("norm", "Normal"), ("expon", "Exponential")])]),

    G("missing_map", "Missingness by variable", "Distribution", ["missing"], status=READY,
      blurb="Percentage missing in each variable, ordered from most to least missing.",
      params=[]),

    # Relationships
    G("scatter_fit", "Scatter with fit", "Relationships", ["correlation", "regression"],
      status=READY,
      params=[P("fit", "Fit", "select", default="linear",
                choices=[("none", "None"), ("linear", "Linear"),
                         ("poly2", "Quadratic")]),
              P("ci_band", "Linear-fit confidence band", "bool", default=True,
                depends={"param": "fit", "equals": "linear"}),
              P("annotate_r", "Annotate Pearson r and p", "bool", default=True,
                depends={"param": "fit", "equals": "linear"})]),

    G("corr_matrix", "Correlation matrix", "Relationships", ["correlation"], status=READY,
      params=[P("show_values", "Show coefficients", "bool", default=True),
              P("mask", "Show", "select", default="lower",
                choices=[("full", "Full"), ("lower", "Lower triangle"),
                         ("upper", "Upper triangle")])]),

    G("residual_plots", "Regression diagnostics", "Relationships", ["regression"],
      status=READY,
      blurb="Residuals against fitted, Q-Q, scale-location and leverage in one panel.",
      params=[P("which", "Panels", "multiselect",
                default=["resid_fitted", "qq", "scale_location", "leverage"],
                choices=[("resid_fitted", "Residuals vs fitted"), ("qq", "Normal Q-Q"),
                         ("scale_location", "Scale-location"),
                         ("leverage", "Residuals vs leverage")])]),

    G("coef_forest", "Coefficient plot", "Relationships",
      ["regression", "pairwise", "proportions", "cox"], status=READY,
      params=[P("log_x", "Log x axis", "bool", default=False,
                help="Ratio measures (odds, risk and hazard ratios) always use a log "
                     "axis with the null line at 1."),
              P("null_line", "Null line at", "number", default=0),
              P("sort", "Sort by estimate", "bool", default=False),
              P("drop_intercept", "Hide intercept", "bool", default=True)]),

    G("pair_grid", "Scatter matrix", "Relationships", ["correlation"],
      params=[P("diag", "Diagonal", "select", default="hist",
                choices=["hist", "kde", "none"])]),

    G("bland_altman", "Bland-Altman plot", "Relationships", ["bland_altman"], status=READY,
      params=[P("show_ci", "Confidence intervals on bias and limits", "bool", default=True)]),

    # Clinical
    G("km_curve", "Kaplan-Meier curve", "Clinical", ["survival"], status=READY,
      params=[P("ci_band", "Confidence bands", "bool", default=True),
              P("at_risk", "Number-at-risk table", "bool", default=True),
              P("p_annotation", "Annotate log-rank p", "bool", default=True),
              P("y_from_zero", "y axis from 0", "bool", default=True,
                help="Truncating the y axis exaggerates separation. Leave this on unless "
                     "events are rare, and say so in the caption if you turn it off."),
              P("xmax", "Maximum time", "number")]),

    G("roc", "ROC curve", "Clinical", ["roc", "regression"], status=READY,
      params=[P("show_auc", "Annotate AUC and interval", "bool", default=True),
              P("diagonal", "Chance line", "bool", default=True),
              P("mark_cutpoint", "Mark the chosen cutpoint", "bool", default=True)]),

    G("pr_curve", "Precision-recall curve", "Clinical", ["roc"],
      params=[P("baseline", "Prevalence baseline", "bool", default=True)]),

    G("calibration", "Calibration plot", "Clinical", ["regression", "roc"],
      params=[P("bins", "Bins", "int", default=10),
              P("loess", "Smooth curve", "bool", default=True),
              P("histogram", "Predicted probability histogram", "bool", default=True)]),

    G("decision_curve", "Decision curve", "Clinical", ["roc", "regression"],
      params=[P("show_all_none", "Show treat-all and treat-none", "bool", default=True)]),

    G("forest", "Forest plot", "Clinical", ["meta", "meta_sensitivity"], status=READY,
      blurb="Study estimates with weight-proportional markers, the pooled diamond, "
            "and heterogeneity statistics in the footer.",
      params=[P("log_x", "Log x axis", "bool", default=True),
              P("prediction_interval", "Draw the prediction interval", "bool", default=True),
              P("marker_scale", "Marker scaling", "number", default=1.0, adv=True),
              P("xlim", "x limits", "text", placeholder="0.2, 5")]),

    G("funnel", "Funnel plot", "Clinical", ["meta", "meta_bias"], status=READY,
      params=[P("contours", "Significance contours", "bool", default=True)]),

    G("forest_effect", "Effect estimate plot", "Clinical",
      ["proportions", "diagnostic", "evalue"], status=READY,
      params=[P("log_x", "Log x axis", "bool", default=False),
              P("null_line", "Null line at", "number", default=1.0)]),

    G("stacked_bar", "Stacked or grouped bar", "Clinical",
      ["categorical", "crosstab", "proportions"], status=READY,
      params=[P("mode", "Mode", "select", default="stacked",
                choices=[("stacked", "Stacked"), ("grouped", "Grouped"),
                         ("filled", "100% stacked")]),
              P("labels", "Show values", "bool", default=True)]),

    G("mosaic", "Mosaic plot", "Clinical", ["categorical", "crosstab"],
      params=[P("shade_residuals", "Shade by residual", "bool", default=True)]),

    G("baujat", "Baujat plot", "Clinical", ["meta", "meta_sensitivity"],
      params=[]),

    # Bench
    G("volcano", "Volcano plot", "Bench", ["diff_expression"],
      params=[P("lfc_threshold", "log2 fold-change line", "number", default=1.0),
              P("p_threshold", "Significance line", "number", default=0.05),
              P("label_top", "Label top features", "int", default=10),
              P("label_genes", "Always label", "text")]),

    G("heatmap", "Heatmap", "Bench", ["diff_expression", "correlation"],
      params=[P("cluster_rows", "Cluster rows", "bool", default=True),
              P("cluster_cols", "Cluster columns", "bool", default=False),
              P("scale", "Scale", "select", default="row",
                choices=[("none", "None"), ("row", "By row (z)"), ("column", "By column")]),
              P("annotate_groups", "Annotate group bar", "column")]),

    G("standard_curve", "Standard curve", "Bench", ["elisa"], status=READY,
      params=[P("log_x", "Log x axis", "bool", default=True),
              P("show_unknowns", "Plot unknowns on the curve", "bool", default=True),
              P("annotate_r2", "Annotate R²", "bool", default=True)]),

    G("plate_heatmap", "Plate layout heatmap", "Bench", ["elisa"], status=READY,
      blurb="96 or 384 well layout coloured by signal. Edge effects are visible here "
            "and nowhere else.",
      params=[P("plate", "Plate format", "select", default="96",
                choices=[("96", "96 well"), ("384", "384 well")]),
              P("annotate", "Show values", "bool", default=True)]),

    G("ct_qc", "Replicate quality control", "Bench", ["qpcr"], status=READY,
      params=[P("threshold", "Flag SD above", "number", default=0.5)]),

    G("dose_curve", "Dose-response curve", "Bench", ["dose_response"],
      params=[P("log_x", "Log dose axis", "bool", default=True),
              P("annotate_ic50", "Annotate IC50", "bool", default=True)]),

    G("pca_biplot", "PCA biplot", "Bench", ["embedding"],
      params=[P("loadings", "Show loading vectors", "bool", default=True),
              P("ellipses", "Group confidence ellipses", "bool", default=True),
              P("label_points", "Label points", "bool", default=False)]),

    G("scree", "Scree plot", "Bench", ["embedding"], status=READY,
      params=[P("cumulative", "Cumulative line", "bool", default=True)]),

    G("embedding", "Embedding scatter", "Bench", ["embedding"], status=READY,
      params=[P("point_size", "Point size", "number", default=20)]),

    G("dendrogram", "Dendrogram", "Bench", ["clustering"],
      params=[P("orientation", "Orientation", "select", default="top",
                choices=["top", "left"]),
              P("colour_threshold", "Colour threshold", "number")]),

    # Reporting diagrams
    G("prisma", "PRISMA flow diagram", "Reporting diagrams", ["screening"], status=READY,
      blurb="Generated from the screening state, so it can never disagree with the "
            "counts in the manuscript.",
      params=[]),

    G("consort", "CONSORT flow diagram", "Reporting diagrams", ["flow"],
      params=[P("arms", "Number of arms", "int", default=2, min=2, max=6)]),

    G("rob_traffic", "Risk of bias traffic light", "Reporting diagrams", ["rob"],
      status=READY,
      params=[]),

    G("power_curve", "Power curve", "Reporting diagrams", ["power"], status=READY,
      params=[P("mark_target", "Mark the target", "bool", default=True),
              P("reference_lines", "Reference lines at 80% and 90%", "bool", default=True)]),

    G("null_distribution", "Permutation null", "Reporting diagrams", ["comparison"],
      status=READY,
      params=[P("mark_observed", "Mark the observed statistic", "bool", default=True)]),

    G("bootstrap_dist", "Bootstrap distribution", "Reporting diagrams", ["comparison"],
      status=READY,
      params=[P("mark_ci", "Shade the interval", "bool", default=True)]),

    G("pvalue_hist", "p value histogram", "Reporting diagrams", ["padjust"], status=READY,
      blurb="A uniform histogram under the null; a spike near zero when there is signal. "
            "Odd shapes point at a problem upstream.",
      params=[P("bins", "Bins", "int", default=20)]),

    G("tost_plot", "Equivalence plot", "Reporting diagrams", ["equivalence"], status=READY,
      params=[P("show_bounds", "Shade the equivalence region", "bool", default=True)]),
]


REGISTRY = index(PLOTS)
GROUPS = group_registry(PLOTS)


def for_kind(kind):
    return [p for p in PLOTS if kind in p["kinds"]]
