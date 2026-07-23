"""
Projects.

Everything in this tool used to accumulate in one undifferentiated pile: one
corpus, one list of datasets, one ledger. That is fine for a single question
and useless the moment you have two, because a systematic review on spinal
cord injury and a re-analysis of somebody's trial data have nothing to do with
each other and should not be able to contaminate each other's PRISMA counts.

A project owns its records, datasets, runs and figures. Switching projects
changes what every pane sees. Nothing is shared except reviewers, who are
people and work across projects, and the settings, which are preferences.

## The progression

A project has a `kind`, and the kind determines its stages. The stages are not
a checklist you tick; each one reports whether it is done by **asking the
database**, so the progress line cannot claim you screened 400 records if the
screen table is empty. A stage can be manually marked done for the ones no
database can verify, like "protocol registered", and that manual flag is
recorded separately from the derived state so the two never get confused.

Stage state is one of:
    done      the derived check passed, or it was manually marked
    active    the first stage that is not done; where you are now
    blocked   an earlier stage it depends on is not done
    waiting   available but not started
"""

import json
import os
import time

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


# ─────────────────────────────────────────────────────────────────────────
#  CRUD
# ─────────────────────────────────────────────────────────────────────────

def create(name, kind="review", question="", registered="", notes=""):
    pid = db.new_id("prj_")
    now = time.time()
    db.insert("project", {
        "id": pid, "name": name.strip() or "Untitled project", "kind": kind,
        "question": question, "registered": registered, "notes": notes,
        "status": "active", "stage_notes": "{}",
        "created_at": now, "updated_at": now,
    })
    log(pid, "created", detail=f"Created as a {KINDS.get(kind, {}).get('label', kind)}.")
    return get(pid)


def get(pid):
    if not pid:
        return None
    p = db.one("SELECT * FROM project WHERE id=?", (pid,))
    if p:
        try:
            p["stage_notes"] = json.loads(p.get("stage_notes") or "{}")
        except Exception:
            p["stage_notes"] = {}
    return p


def update(pid, patch, expected_revision=None):
    current = get(pid)
    if not current:
        return None
    revision = int(current.get("revision") or 1)
    if expected_revision is not None and int(expected_revision) != revision:
        raise RuntimeError("Project changed since it was loaded.")
    allowed = ("name", "kind", "question", "registered", "notes", "status")
    sets, args = [], []
    for k in allowed:
        if k in patch:
            sets.append(f"{k}=?")
            args.append(patch[k])
    if sets:
        sets.append("updated_at=?")
        args.append(time.time())
        sets.append("revision=?")
        args.append(revision + 1)
        args.append(pid)
        db.exec_(f"UPDATE project SET {','.join(sets)} WHERE id=?", tuple(args))
    return get(pid)


def listing(include_archived=False):
    sql = "SELECT * FROM project"
    if not include_archived:
        sql += " WHERE status IS NULL OR status != 'archived'"
    sql += " ORDER BY updated_at DESC"
    out = []
    for p in db.query(sql):
        pid = p["id"]
        prog = progress(pid)
        p["counts"] = counts(pid)
        p["progress"] = {"done": prog["n_done"], "total": prog["n_total"],
                         "percent": prog["percent"], "current": prog["current"]}
        out.append(p)
    return out


def counts(pid):
    from . import screening
    ft = screening._final_screen_states(pid, "full_text")
    included = sum(1 for x in ft.values() if x.get("final") and x.get("decision") == "include")
    return {
        "records": _c("SELECT COUNT(*) c FROM record WHERE project_id IS ?", (pid,)),
        "datasets": _c("SELECT COUNT(*) c FROM dataset WHERE project_id IS ?", (pid,)),
        "runs": _c("SELECT COUNT(*) c FROM analysis_run WHERE project_id IS ? "
                   "AND status='ok'", (pid,)),
        "figures": _c("SELECT COUNT(*) c FROM figure WHERE project_id IS ?", (pid,)),
        "included": included,
    }


def delete(pid, purge=True):
    """Removing a project removes its records by cascade. Datasets, runs and
    figures are referenced loosely rather than by foreign key, so they are
    handled here explicitly: purge deletes them, otherwise they are released
    back to the unfiled bucket rather than silently vanishing."""
    n = counts(pid)
    if purge:
        figs = db.query("SELECT path FROM figure WHERE project_id IS ?", (pid,))
        dsets = db.query("SELECT id,path FROM dataset WHERE project_id IS ?", (pid,))
        with db.transaction():
            db.exec_("DELETE FROM figure WHERE project_id IS ?", (pid,))
            db.exec_("DELETE FROM analysis_run WHERE project_id IS ?", (pid,))
            db.exec_("DELETE FROM dataset WHERE project_id IS ?", (pid,))
            db.exec_("DELETE FROM project WHERE id=?", (pid,))
        for row in figs + dsets:
            path = row.get("path")
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
    else:
        with db.transaction():
            for t in ("figure", "analysis_run", "dataset"):
                db.exec_(f"UPDATE {t} SET project_id=NULL WHERE project_id IS ?", (pid,))
            db.exec_("DELETE FROM project WHERE id=?", (pid,))
    return {"deleted": n, "purged": purge}


# ─────────────────────────────────────────────────────────────────────────
#  Progression
# ─────────────────────────────────────────────────────────────────────────

def set_stage_note(pid, stage, note=None, manual_done=None):
    p = get(pid)
    if not p:
        return None
    notes = p["stage_notes"]
    entry = notes.get(stage, {})
    if note is not None:
        entry["note"] = note
    if manual_done is not None:
        entry["done"] = bool(manual_done)
        log(pid, "stage", stage=stage,
            detail=("marked done" if manual_done else "unmarked"))
    notes[stage] = entry
    db.exec_("UPDATE project SET stage_notes=?, updated_at=? WHERE id=?",
             (json.dumps(notes), time.time(), pid))
    return get(pid)


def progress(pid):
    p = get(pid)
    if not p:
        return {"stages": [], "n_done": 0, "n_total": 0, "percent": 0, "current": None}
    pipeline = PIPELINES.get(p.get("kind") or "review", PIPELINES["review"])
    notes = p["stage_notes"]
    stages, n_done = [], 0
    first_open = None
    for key in pipeline:
        label, check, blurb = STAGE_DEFS[key]
        manual = bool(notes.get(key, {}).get("done"))
        if check is None:
            derived, detail = False, ""
        else:
            derived, detail = check(pid)
        done = derived or manual
        if done:
            n_done += 1
        elif first_open is None:
            first_open = key
        stages.append({
            "id": key, "label": label, "blurb": blurb,
            "done": done, "derived": derived, "manual": manual,
            "detail": detail,
            "note": notes.get(key, {}).get("note", ""),
            "manual_only": check is None,
        })
    for s in stages:
        s["state"] = ("done" if s["done"]
                      else "active" if s["id"] == first_open
                      else "waiting")
        s["status"] = ("complete" if s["done"] else
                       "in_progress" if s["id"] == first_open else "blocked")
        s["completion_rule"] = STAGE_DEFS[s["id"]][2]
    return {"stages": stages, "n_done": n_done, "n_total": len(stages),
            "percent": round(100 * n_done / max(1, len(stages))),
            "current": first_open,
            "kind": p.get("kind"), "pipeline": pipeline}


def log(pid, kind, stage=None, detail=""):
    db.insert("project_event", {"id": db.new_id("ev_"), "project_id": pid,
                                "kind": kind, "stage": stage, "detail": detail,
                                "at": time.time()})


def timeline(pid, limit=60):
    return db.query("SELECT * FROM project_event WHERE project_id IS ? "
                    "ORDER BY at DESC LIMIT ?", (pid, limit))


# ─────────────────────────────────────────────────────────────────────────
#  Adoption of unfiled work
# ─────────────────────────────────────────────────────────────────────────

def unfiled():
    """Anything created before projects existed, or released by a deletion."""
    return {
        "records": _c("SELECT COUNT(*) c FROM record WHERE project_id IS NULL", ()),
        "datasets": _c("SELECT COUNT(*) c FROM dataset WHERE project_id IS NULL", ()),
        "runs": _c("SELECT COUNT(*) c FROM analysis_run WHERE project_id IS NULL", ()),
        "figures": _c("SELECT COUNT(*) c FROM figure WHERE project_id IS NULL", ()),
    }


def adopt_unfiled(pid, what=("records", "datasets", "runs", "figures")):
    """Assign everything currently unfiled to a project, so an existing
    database is not stranded when projects arrive."""
    table = {"records": "record", "datasets": "dataset",
             "runs": "analysis_run", "figures": "figure"}
    moved = {}
    for key in what:
        t = table.get(key)
        if not t:
            continue
        n = _c(f"SELECT COUNT(*) c FROM {t} WHERE project_id IS NULL", ())
        db.exec_(f"UPDATE {t} SET project_id=? WHERE project_id IS NULL", (pid,))
        moved[key] = n
    if any(moved.values()):
        log(pid, "milestone",
            detail="Adopted unfiled work: " +
                   ", ".join(f"{v} {k}" for k, v in moved.items() if v))
    return moved
