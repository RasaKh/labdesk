"""Deterministic analysis compatibility guide.

This module deliberately does *not* choose a statistical method for the user.
It connects two declarative sources LabDesk already trusts:

* the reviewed variable dictionary says what each dataset column is; and
* the statistics registry says what variable roles each method accepts.

The result is constraint matching: which READY methods can be populated from
this dataset, and which role assignments are structurally compatible with the
variables the researcher has selected. Scientific intent, estimands, causal
claims and final method choice remain human decisions.
"""

from __future__ import annotations

GOALS = {
    "describe": {
        "label": "Describe / check data",
        "blurb": "Summaries, distributions, missingness and basic assumption checks.",
        "groups": {"Descriptives", "Assumption checks"},
        "exclude": {"power_achieved"},
        "primary_label": "Variable to focus on",
        "secondary_label": "Optional grouping variable",
        "primary_roles": ("vars", "dv", "var", "row"),
        "secondary_roles": ("group", "col"),
    },
    "compare": {
        "label": "Compare groups",
        "blurb": "Independent-group comparisons for continuous or categorical outcomes.",
        "groups": {"Two groups", "Three or more groups", "Categorical and proportions",
                   "Bayesian and equivalence"},
        # Paired/repeated procedures have their own intent below. One-sample
        # procedures do not compare dataset groups.
        "exclude": {"ttest_paired", "wilcoxon", "ttest_1samp", "wilcoxon_1samp",
                    "mcnemar", "cochran_q", "friedman", "binomial", "goodness_fit"},
        "primary_label": "Outcome",
        "secondary_label": "Group / exposure",
        "primary_roles": ("dv", "outcome", "row"),
        "secondary_roles": ("group", "ordered", "col"),
    },
    "paired": {
        "label": "Paired / repeated measurements",
        "blurb": "Measurements linked within the same subjects or units.",
        "include": {"ttest_paired", "wilcoxon", "mcnemar", "cochran_q", "friedman",
                    "bland_altman"},
        "primary_label": "First measurement / outcome",
        "secondary_label": "Second measurement / within factor",
        "primary_roles": ("a", "dv", "vars"),
        "secondary_roles": ("b", "within", "vars"),
    },
    "association": {
        "label": "Association / relationship",
        "blurb": "Associations between variables without declaring one to be an outcome model.",
        "include": {"correlation", "crosstab", "chi2", "fisher", "armitage"},
        "primary_label": "First variable",
        "secondary_label": "Second variable",
        "primary_roles": ("vars", "row", "outcome"),
        "secondary_roles": ("vars", "col", "ordered"),
    },
    "agreement": {
        "label": "Agreement / reliability",
        "blurb": "Agreement between methods or raters and reliability of repeated measures/items.",
        "include": {"icc", "bland_altman", "kappa", "cronbach"},
        "primary_label": "First measure / item",
        "secondary_label": "Second measure / rater",
        "primary_roles": ("a", "value", "raters", "items"),
        "secondary_roles": ("b", "rater", "raters", "items"),
    },
    "model": {
        "label": "Model an outcome",
        "blurb": "Regression models where one variable is explicitly the outcome.",
        "groups": {"Regression"},
        "primary_label": "Outcome",
        "secondary_label": "Optional predictor to prefill",
        "primary_roles": ("dv",),
        "secondary_roles": ("predictors",),
    },
    "survival": {
        "label": "Time-to-event",
        "blurb": "Survival/time-to-event analyses using a time variable and event indicator.",
        "groups": {"Survival"},
        "primary_label": "Follow-up / survival time",
        "secondary_label": "Event indicator",
        "primary_roles": ("time",),
        "secondary_roles": ("event",),
    },
    "diagnostic": {
        "label": "Diagnostic / prediction performance",
        "blurb": "Accuracy of a score or binary test against a binary reference outcome.",
        "groups": {"Diagnostic accuracy and prediction"},
        "primary_label": "Reference / truth",
        "secondary_label": "Score / test",
        "primary_roles": ("truth",),
        "secondary_roles": ("score", "test"),
    },
    "meta": {
        "label": "Meta-analysis dataset",
        "blurb": "Study-level effect estimates and their uncertainty.",
        "groups": {"Meta-analysis"},
        "primary_label": "Effect estimate",
        "secondary_label": "Standard error",
        "primary_roles": ("effect",),
        "secondary_roles": ("se",),
    },
    "bench": {
        "label": "Bench / omics",
        "blurb": "Structured assay and multivariate workflows whose required columns are declared by each method.",
        "groups": {"Bench and omics"},
        "primary_label": "Variable to focus on",
        "secondary_label": "Second variable",
        "primary_roles": ("ct", "od", "vars"),
        "secondary_roles": ("gene", "conc", "colour"),
    },
}


def public_goals():
    """Browser-safe description of the deterministic intents."""
    return [{"id": gid, "label": g["label"], "blurb": g["blurb"],
             "primary_label": g["primary_label"],
             "secondary_label": g["secondary_label"]}
            for gid, g in GOALS.items()]
