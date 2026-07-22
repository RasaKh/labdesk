"""Projects: the full stage pipeline with all derived checks."""

import json

from . import db

# ─────────────────────────────────────────────────────────────────────────
#  Stage definitions per project kind
#
#  `check` receives the project id and returns (done, detail). Detail is a
#  short human sentence shown under the stage, always counted from real rows.
# ─────────────────────────────────────────────────────────────────────────

KINDS = {
    "review": {
        "label": "Systematic review",
        "blurb": "Search, screen, extract, appraise, synthesise. The full arc.",
        "stain": "trypan",
    },
    "analysis": {
        "label": "Data analysis",
        "blurb": "Your own dataset, from import through figures to a methods paragraph.",
        "stain": "methylene",
    },
    "mixed": {
        "label": "Mixed",
        "blurb": "Both: a review that also analyses primary data.",
        "stain": "haem",
    },
}


def _c(sql, args=()):
    r = db.one(sql, args)
    return (r or {}).get("c", 0)


# ── derived checks ───────────────────────────────────────────────────────

def _has_question(pid):
    p = get(pid)
    ok = bool(p and (p.get("question") or "").strip())
    return ok, ("Question recorded." if ok else "No question written yet.")


def _has_registration(pid):
    p = get(pid)
    r = (p or {}).get("registered") or ""
    return bool(r.strip()), (f"Registered as {r}." if r.strip()
                             else "Not registered. PROSPERO for reviews, OSF otherwise.")


def _has_search(pid):
    n = _c("SELECT COUNT(*) c FROM harvest_query WHERE project_id IS ?", (pid,))
    recs = _c("SELECT COUNT(*) c FROM record WHERE project_id IS ?", (pid,))
    return (n > 0 and recs > 0), (f"{n} searches run, {recs} records held."
                                  if n else "No searches run yet.")


def _has_dedup(pid):
    total = _c("SELECT COUNT(*) c FROM record WHERE project_id IS ?", (pid,))
    dupes = _c("SELECT COUNT(*) c FROM record WHERE project_id IS ? "
               "AND dedup_of IS NOT NULL", (pid,))
    ran = _c("SELECT COUNT(*) c FROM project_event WHERE project_id IS ? "
             "AND stage='dedup'", (pid,))
    done = total > 0 and (dupes > 0 or ran > 0)
    return done, (f"{dupes} duplicates marked, {total - dupes} unique."
                  if done else "Not deduplicated." if total else "No records yet.")


def _has_ta_screen(pid):
    n = _c("SELECT COUNT(DISTINCT s.record_id) c FROM screen s JOIN record r "
           "ON r.id = s.record_id WHERE r.project_id IS ? AND s.stage='title_abstract'",
           (pid,))
    total = _c("SELECT COUNT(*) c FROM record WHERE project_id IS ? AND dedup_of IS NULL",
               (pid,))
    return (total > 0 and n >= total), (f"{n} of {total} screened."
                                        if total else "No records to screen.")


def _has_ft_screen(pid):
    from . import screening
    ta = screening._final_screen_states(pid, "title_abstract")
    eligible = {rid for rid, x in ta.items()
                if x.get("final") and x["decision"] in ("include", "maybe")}
    ft = screening._final_screen_states(pid, "full_text")
    n = sum(1 for rid in eligible
            if ft.get(rid, {}).get("final") and
            ft.get(rid, {}).get("decision") in ("include", "exclude"))
    total = len(eligible)
    return (total > 0 and n >= total), (f"{n} of {total} full texts assessed."
                                       if total else "No records advanced to full text.")


def _has_extraction(pid):
    from . import screening
    n = _c("SELECT COUNT(*) c FROM extraction e JOIN record r ON r.id = e.record_id "
           "WHERE r.project_id IS ?", (pid,))
    ft = screening._final_screen_states(pid, "full_text")
    included = sum(1 for x in ft.values() if x.get("final") and x["decision"] == "include")
    return (included > 0 and n >= included), (f"{n} of {included} included studies extracted."
                                               if included else "No included studies yet.")


def _has_rob(pid):
    from . import screening
    n = _c("SELECT COUNT(*) c FROM rob rb JOIN record r ON r.id = rb.record_id "
           "WHERE r.project_id IS ?", (pid,))
    ft = screening._final_screen_states(pid, "full_text")
    included = sum(1 for x in ft.values() if x.get("final") and x["decision"] == "include")
    return (included > 0 and n >= included), (f"{n} of {included} appraised." if included
                                               else "No included studies yet.")


def _has_dataset(pid):
    n = _c("SELECT COUNT(*) c FROM dataset WHERE project_id IS ?", (pid,))
    return n > 0, (f"{n} dataset{'s' if n != 1 else ''} imported."
                   if n else "No data imported.")


def _has_dictionary(pid):
    rows = db.query("SELECT dictionary FROM dataset WHERE project_id IS ?", (pid,))
    if not rows:
        return False, "No data imported."
    # A dictionary counts as reviewed once at least one column carries a
    # non-empty role or note, which only happens by hand.
    touched = 0
    for r in rows:
        try:
            d = json.loads(r["dictionary"] or "{}")
        except Exception:
            continue
        if any((v.get("role") or v.get("notes")) for v in d.values()):
            touched += 1
    return touched > 0, (f"{touched} of {len(rows)} dictionaries annotated."
                         if touched else "Types inferred but not reviewed.")


def _has_analysis(pid):
    n = _c("SELECT COUNT(*) c FROM analysis_run WHERE project_id IS ? AND status='ok'",
           (pid,))
    return n > 0, (f"{n} analyses in the ledger." if n else "Nothing run yet.")


def _has_synthesis(pid):
    n = _c("SELECT COUNT(*) c FROM analysis_run WHERE project_id IS ? AND status='ok' "
           "AND test_id LIKE 'meta%'", (pid,))
    return n > 0, (f"{n} syntheses run." if n else "No meta-analysis run.")


def _has_figures(pid):
    n = _c("SELECT COUNT(*) c FROM figure WHERE project_id IS ?", (pid,))
    return n > 0, (f"{n} figures rendered." if n else "No figures yet.")


STAGE_DEFS = {
    "define":       ("Define the question", _has_question,
                     "A written question, in PICO form for a review."),
    "register":     ("Register the protocol", _has_registration,
                     "PROSPERO for reviews, OSF otherwise. Manual: tick it once done."),
    "search":       ("Search", _has_search,
                     "Run at least one search and hold the results."),
    "dedup":        ("Deduplicate", _has_dedup,
                     "Collapse the same study appearing from several sources."),
    "screen_ta":    ("Screen titles and abstracts", _has_ta_screen,
                     "Every unique record judged at least once."),
    "screen_ft":    ("Screen full texts", _has_ft_screen,
                     "Assess what survived, and record a reason for each exclusion."),
    "extract":      ("Extract", _has_extraction,
                     "Structured fields, not notes, so they convert to effect sizes."),
    "appraise":     ("Appraise risk of bias", _has_rob,
                     "One instrument per design, judged per domain."),
    "synthesise":   ("Synthesise", _has_synthesis,
                     "Pool, or decide not to and say why."),
    "import":       ("Import data", _has_dataset,
                     "One row per observation, one column per variable."),
    "dictionary":   ("Review the variable dictionary", _has_dictionary,
                     "Correct the inferred types before anything else."),
    "analyse":      ("Analyse", _has_analysis,
                     "Run tests. The gate checks assumptions before each one."),
    "figures":      ("Draw figures", _has_figures,
                     "Built from results, so annotation matches the statistics."),
    "report":       ("Report", None,
                     "Methods paragraph, checklist, bundle. Tick when submitted."),
}

PIPELINES = {
    "review":   ["define", "register", "search", "dedup", "screen_ta", "screen_ft",
                 "extract", "appraise", "synthesise", "report"],
    "analysis": ["define", "register", "import", "dictionary", "analyse", "figures",
                 "report"],
    "mixed":    ["define", "register", "search", "dedup", "screen_ta", "screen_ft",
                 "extract", "appraise", "import", "dictionary", "analyse", "figures",
                 "synthesise", "report"],
}
