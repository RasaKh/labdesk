"""The handbook.

Reference material that travels with the tool: the thing that tells
you how to run a review sits next to the thing that runs it. Entries are
plain data, starting with the overview of how the pieces fit together."""

SECTIONS = [
    ("Start here", "haem"),
    ("Doing a review", "trypan"),
    ("Choosing and running a test", "methylene"),
    ("Reading what comes back", "eosin"),
    ("Producing the output", "fastgreen"),
]


def E(id, title, section, summary, body, reading=None, panes=None):
    return {"id": id, "title": title, "section": section, "summary": summary,
            "body": body.strip(), "reading": reading or "", "panes": panes or []}


ENTRIES = [

# ═══════════════════════════════════════════════════════════════════════
E("overview", "How the pieces fit together", "Start here",
  "Nine panes, two workflows, one ledger underneath both.",
  """
There are two jobs this tool does, and they meet in the middle.

**The evidence workflow** starts with a question and ends with a pooled
estimate: search the literature, screen what comes back, extract numbers from
what survives, judge how much to trust it, and synthesise. That runs left to
right through Harvest, Screening and Synthesis.

**The analysis workflow** starts with a dataset and ends with a figure and a
paragraph: import, check the variables, run a test, draw it, report it. That
runs through Data, Statistics and Figures.

They meet at **Synthesis**, where extracted arm-level numbers become effect
sizes and standard errors, and those go straight into the meta-analysis in the
Statistics pane like any other data.

## What holds it together

Underneath both sits the **run ledger**. Every analysis writes one row: a hash
of the data, the exact specification, the random seed, the package versions,
the assumption checks, and the result. Nothing runs without leaving that trace.

Three things fall out of it that are hard to get any other way.

- The **methods paragraph** is assembled from the ledger, so it describes what
  was actually executed rather than what you meant to do.
- The **multiplicity audit** knows how many tests have been run against a given
  dataset, and can say what that does to your alpha.
- The **reproducibility bundle** contains the data hash, every spec, every
  result, the figures, and generated Python and R that re-runs all of it.

> The ledger is the reason this is a research tool rather than a calculator.
> A calculator gives you a number. This also records that you asked.

## The panes

| Pane | What it is for |
|---|---|
| Data | Import, and get the variable types right before anything else |
| Statistics | The test library, with an assumption gate in front of it |
| Figures | Publication figures built from a result, not from raw data |
| Harvest | Live searches against PubMed, Europe PMC, registries and more |
| Screening | Title/abstract and full-text screening, with agreement stats |
| Synthesis | Extraction forms, risk of bias, conversion to effect sizes |
| Report | Methods text, checklists, pre-registration, the bundle |
| Run ledger | Everything that has been executed, and what to delete |
| Settings | Statistical defaults, API keys, scale, and the danger zone |

[Open the Data pane](#pane:data) to start an analysis, or
[Harvest](#pane:harvest) to start a review.
""", reading="3 min", panes=["data", "harvest"]),

# ═══════════════════════════════════════════════════════════════════════
E("first-analysis", "Your first analysis, end to end", "Start here",
  "Import, check types, run, draw, report. About ten minutes.",
  """
## 1. Import

[Data pane](#pane:data). Drop in a CSV, or give a path on the server. One row
per observation, one column per variable, a header row. Missing cells can be
empty, `NA`, `.`, `999`, or a dozen other conventions; they are all recognised.

## 2. Fix the dictionary

This is the step people skip, and it is the one that quietly ruins results.

Each column gets an inferred type: continuous, ordinal, categorical, binary,
time, or id. That type decides which tests will accept the variable. The
classic failure is a 0/1 outcome read as continuous, which then happily goes
into a t-test as if it were a measurement.

Look down the **type** column and correct anything wrong before you go further.
Also glance at **missing %**, which is flagged in amber above 20%.

## 3. Pick a test

[Statistics pane](#pane:stats). The library is grouped by what you are asking,
not by test name. If you are unsure, read
[Choosing a test](#entry:choosing).

Assign your variables to the test's **roles**. Only variables of the right type
are offered, which is the dictionary paying off.

## 4. Read the gate

Before anything runs, the assumptions the test rests on are checked against
your actual data, and shown as a row of lozenges.

- **Green** the assumption holds
- **Amber** it is borderline, or untestable and worth thinking about
- **Red** it fails, and the tool names the test that does not need it

Red does not always mean stop. It means make a decision and be able to defend
it. See [When an assumption fails](#entry:assumptions).

## 5. Run

The result shows the statistic, the p value, effect sizes with intervals, and a
sentence formatted correctly for a manuscript. Click the sentence to copy it.

The right-hand inspector shows the equivalent **Python and R**, so the analysis
is auditable by someone who does not have this installed.

## 6. Draw it

[Figures pane](#pane:figures). Figures are built from the result, so the
significance annotation can never disagree with the statistics that produced
it. Pick a size preset that matches your target journal: 89 mm single column,
183 mm double.

## 7. Report

[Report pane](#pane:report). Generate the methods paragraph, tick through the
relevant checklist, and build the bundle.
""", reading="5 min", panes=["data", "stats", "figures", "report"]),

]
