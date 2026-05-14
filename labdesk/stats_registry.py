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
]


REGISTRY = index(TESTS)
GROUPS = group_registry(TESTS)


def get(test_id):
    return REGISTRY.get(test_id)


def ready_count():
    return sum(1 for t in TESTS if t["status"] == READY)