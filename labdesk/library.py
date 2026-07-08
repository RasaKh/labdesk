"""The handbook.

Reference material that travels with the tool, so the thing that tells you
how to run a review sits next to the thing that runs it. Two halves: doing a
review (the whole arc, then specific search and screening steps) and the
statistics. Entries are plain data; `body` is a small markdown subset."""

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

# ═══════════════════════════════════════════════════════════════════════
E("review-arc", "A systematic review, start to finish", "Doing a review",
  "The whole arc in order, with the pane that handles each step.",
  """
A review has an order, and most of the pain in doing one comes from doing the
steps out of order. This is the order.

## 0. Write the protocol first

Before any searching. Define the question in PICO form, the inclusion and
exclusion criteria, the outcomes, and the analysis plan. Register it on
PROSPERO.

This is not bureaucracy. A protocol written after the search is a protocol
written knowing what the literature contains, which is how reviews end up
answering the question the evidence happens to fit.

> Search PROSPERO from [Harvest](#pane:harvest) first. If your review already
> exists and is in progress, better to find out now.

Draft the analysis plan from [Report](#pane:report), which produces a
pre-registration skeleton.

## 1. Build the search

[Harvest](#pane:harvest). One database is never enough for a review. The
conventional minimum is MEDLINE (via PubMed), Embase, and CENTRAL, plus trial
registries. Here you have PubMed, Europe PMC, OpenAlex, Crossref, bioRxiv and
medRxiv, ClinicalTrials.gov and openFDA.

Run each source separately and let the corpus accumulate. See
[Building a search](#entry:search) for the syntax.

Record the date you searched. You will need it for the PRISMA diagram, and you
will need to re-run the search before submission if enough time passes.

## 2. Deduplicate

One click in the corpus panel. Duplicates are caught by DOI first, then by
fuzzy title match within publication year. Cross-source overlap is heavy;
expect 20-40% of a multi-source corpus to be duplicates.

## 3. Trim, if the search over-reached

If a search came back far wider than intended, the **trim panel** narrows the
corpus with a preview: it counts what it would remove and shows a sample before
anything goes. Common trims are records with no abstract, records before a
cut-off year, and animal-only work.

Be careful here. Trimming after seeing titles is a form of screening, and
should be done with the same criteria you wrote in the protocol, not by feel.

## 4. Screen titles and abstracts

[Screening](#pane:screen). Keyboard-driven: `i` include, `e` exclude, `m`
maybe, `s` skip, `u` undo. Undo genuinely deletes the judgement.

Screen liberally at this stage. The cost of wrongly including something is one
full text to read. The cost of wrongly excluding it is a missing study nobody
will ever find.

Two reviewers should screen independently. See
[Dual screening and agreement](#entry:dual).

## 5. Screen full texts

Switch the stage selector to **Full text**. Only records included or marked
maybe at title/abstract appear.

Now record a **reason** for every exclusion. PRISMA requires reasons at this
stage and not before, and the reason list feeds straight into the flow diagram.

## 6. Extract

[Synthesis](#pane:synthesis). Pick a form: randomised trial, observational, or
diagnostic accuracy. Extract into structured fields rather than notes, because
structured fields convert into effect sizes and notes do not.

Extract in duplicate if you can. If you cannot, extract once and have a second
person check a sample.

## 7. Judge risk of bias

Same pane. Pick the instrument that matches the design:

| Design | Instrument |
|---|---|
| Randomised trial | RoB 2 |
| Non-randomised intervention study | ROBINS-I |
| Cohort or case-control | Newcastle-Ottawa |
| Diagnostic accuracy | QUADAS-2 |

Judge per domain with a written rationale. The overall judgement is derived
from the domains, not decided separately.

## 8. Synthesise

Convert extractions to effect sizes in the Synthesis pane, then run
[Meta-analysis](#entry:meta) from the Statistics pane. Or decide not to pool:
see when that is the right call in the same entry.

## 9. Report

[Report](#pane:report). The PRISMA diagram is drawn from the screening
database, so it cannot disagree with what you actually did. Work through the
PRISMA checklist. Export the bundle.
""", reading="8 min", panes=["harvest", "screen", "synthesis", "report"]),

# ═══════════════════════════════════════════════════════════════════════
E("search", "Building a search that finds things", "Doing a review",
  "PICO, field tags, MeSH, and why sensitivity beats precision here.",
  """
A search for a review is not a search for a paper to read. You are trying not
to miss anything, which means accepting a lot of irrelevant results.

## Start from PICO

Break the question into concepts, then build each concept as a block of
synonyms joined by `OR`, and join the blocks with `AND`.

```
(spinal cord injury OR SCI OR myelopathy)
AND (olfactory ensheathing cell* OR OEC OR olfactory glia)
AND (transplant* OR graft* OR implant*)
```

Three or four concept blocks is usually right. More than that and you are
almost certainly excluding relevant work.

## Use both free text and controlled vocabulary

PubMed indexes with MeSH terms. Controlled vocabulary catches papers whose
title and abstract use different words; free text catches papers too new to
have been indexed yet. You want both.

```
("Spinal Cord Injuries"[Mesh] OR spinal cord injur*[tiab])
```

- `[tiab]` title and abstract
- `[Mesh]` indexed subject heading
- `[Mesh:noexp]` that heading without narrower terms
- `[pt]` publication type
- `[dp]` date of publication

## What the controls do

The Harvest pane's fields write into the query for you:

- **Publication types** appends `"Randomized Controlled Trial"[Publication Type]`
- **Species** appends the human or animal MeSH filter
- **Abstract only** appends `hasabstract`, which is a reasonable default but
  will drop conference abstracts and some older records
- **From / to year** appends a date range

The query actually sent back is shown in the result, so you can paste it into
the manuscript. You will need it: PRISMA requires the full strategy for at
least one database.

## Then go wider

Databases are not enough on their own.

- **Trial registries** catch studies that were run and never published, which
  is exactly the population publication bias removes
- **Preprints** via bioRxiv and medRxiv
- **Backward citation chasing** take the reference lists of your included
  studies. Crossref returns them
- **Forward citation chasing** who has cited your included studies since.
  OpenAlex and Europe PMC both give citation counts and links

## Then check what you found is real

Run the **retraction check** in the corpus panel. It queries Crossref, which
carries the Retraction Watch data, and flags retractions and expressions of
concern. Citing a retracted trial in a meta-analysis is a real and recurring
failure, and it is entirely avoidable.

Run **resolve open access** to turn DOIs into legal full-text links via
Unpaywall, which needs only an email address in Settings.
""", reading="6 min", panes=["harvest"]),

]
