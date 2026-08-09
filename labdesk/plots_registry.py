"""
PLOT_REGISTRY.

Same contract as the test registry. Each plot declares which result kinds
it can render, its own parameters, and whether it is implemented.
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

]

REGISTRY = index(PLOTS)
GROUPS = group_registry(PLOTS)

def for_kind(kind):
    return [p for p in PLOTS if kind in p["kinds"]]
