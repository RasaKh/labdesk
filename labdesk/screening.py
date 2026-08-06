"""
Evidence synthesis: deduplication, screening state, PRISMA counts,
extraction forms and risk-of-bias instruments.

The PRISMA numbers are derived from the database, never typed in. That means
the diagram in the manuscript cannot drift out of step with what actually
happened, which is the usual failure mode when the flow chart is drawn by
hand at the end.
"""

import json
import hashlib
import re
import time

from . import db
from .schema import P, index

# ─────────────────────────────────────────────────────────────────────────
#  Deduplication
# ─────────────────────────────────────────────────────────────────────────

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def normalise_title(t):
    t = _PUNCT.sub(" ", (t or "").lower())
    return _WS.sub(" ", t).strip()


def _similar(a, b):
    try:
        from rapidfuzz import fuzz
        return fuzz.token_sort_ratio(a, b) / 100
    except Exception:
        from difflib import SequenceMatcher
        return SequenceMatcher(None, a, b).ratio()


def deduplicate(project_id=None, threshold=0.93, ctl=None):
    rows = db.query("SELECT id, doi, title, year, journal FROM record "
                    "WHERE project_id IS ? AND dedup_of IS NULL", (project_id,))
    by_doi = {}
    dupes = []
    for r in rows:
        d = (r["doi"] or "").strip().lower()
        if d:
            if d in by_doi:
                dupes.append((r["id"], by_doi[d], "doi"))
            else:
                by_doi[d] = r["id"]
    marked = {d[0] for d in dupes}
    remaining = [r for r in rows if r["id"] not in marked]
    # Blocking on year keeps this from being quadratic across the whole corpus.
    buckets = {}
    for r in remaining:
        buckets.setdefault(r["year"], []).append(r)
    for yi, (yr, group) in enumerate(buckets.items()):
        if ctl:
            ctl.check()
            ctl.progress(100 * yi / max(1, len(buckets)), f"Year {yr}")
        norms = [(r, normalise_title(r["title"])) for r in group]
        for i in range(len(norms)):
            for j in range(i + 1, len(norms)):
                if norms[i][0]["id"] in marked or norms[j][0]["id"] in marked:
                    continue
                if abs(len(norms[i][1]) - len(norms[j][1])) > 20:
                    continue
                if _similar(norms[i][1], norms[j][1]) >= threshold:
                    dupes.append((norms[j][0]["id"], norms[i][0]["id"], "title"))
                    marked.add(norms[j][0]["id"])
    for dup_id, keep_id, how in dupes:
        db.exec_("UPDATE record SET dedup_of=? WHERE id=?", (keep_id, dup_id))
    if project_id is not None:
        try:
            from . import projects
            projects.log(project_id, "milestone", stage="dedup",
                         detail=f"Deduplication run: {len(dupes)} duplicates marked.")
        except Exception:
            pass
    return {"n_records": len(rows), "n_duplicates": len(dupes),
            "by_doi": sum(1 for d in dupes if d[2] == "doi"),
            "by_title": sum(1 for d in dupes if d[2] == "title"),
            "n_unique": len(rows) - len(dupes)}



# ─────────────────────────────────────────────────────────────────────────
#  Reviewers
#
#  A reviewer is a stored identity rather than a string typed into a box on
#  every visit. That matters for three reasons: decisions attach to a stable
#  id so a typo cannot silently create a third reviewer, the interface can
#  show each person's progress, and blind mode has something to hide.
# ─────────────────────────────────────────────────────────────────────────

REVIEWER_COLOURS = ["haem", "eosin", "methylene", "fastgreen", "safranin", "crystal"]


def _initials(name):
    parts = [p for p in re.split(r"[\s._-]+", name.strip()) if p]
    if not parts:
        return "??"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def ensure_reviewers():
    """First run gets two, because dual screening is the default expectation
    and an interface that starts with one quietly encourages screening alone."""
    if db.query("SELECT id FROM reviewer LIMIT 1"):
        return
    for i, name in enumerate(("Reviewer 1", "Reviewer 2")):
        db.insert("reviewer", {"id": db.new_id("rev_"), "name": name,
                               "initials": f"R{i+1}", "role": "screener",
                               "colour": REVIEWER_COLOURS[i], "created_at": time.time()})


def reviewers(project_id=None):
    ensure_reviewers()
    rows = db.query("SELECT * FROM reviewer ORDER BY created_at")
    for r in rows:
        if project_id is None:
            done = db.one("SELECT COUNT(*) c FROM screen WHERE reviewer=?", (r["id"],))
            ta = db.one("SELECT COUNT(*) c FROM screen WHERE reviewer=? AND stage='title_abstract'",
                        (r["id"],))
            ft = db.one("SELECT COUNT(*) c FROM screen WHERE reviewer=? AND stage='full_text'",
                        (r["id"],))
        else:
            base = (" FROM screen s JOIN record rec ON rec.id=s.record_id "
                    "WHERE rec.project_id IS ? AND s.reviewer=?")
            args = (project_id, r["id"])
            done = db.one("SELECT COUNT(*) c" + base, args)
            ta = db.one("SELECT COUNT(*) c" + base + " AND s.stage='title_abstract'", args)
            ft = db.one("SELECT COUNT(*) c" + base + " AND s.stage='full_text'", args)
        r["decisions"] = done["c"] if done else 0
        r["title_abstract"] = ta["c"] if ta else 0
        r["full_text"] = ft["c"] if ft else 0
    return rows


def add_reviewer(name, role="screener"):
    existing = reviewers()
    colour = REVIEWER_COLOURS[len(existing) % len(REVIEWER_COLOURS)]
    rid = db.new_id("rev_")
    db.insert("reviewer", {"id": rid, "name": name.strip() or "Unnamed",
                           "initials": _initials(name), "role": role,
                           "colour": colour, "created_at": time.time()})
    return db.one("SELECT * FROM reviewer WHERE id=?", (rid,))


def rename_reviewer(rid, name):
    db.exec_("UPDATE reviewer SET name=?, initials=? WHERE id=?",
             (name, _initials(name), rid))
    return db.one("SELECT * FROM reviewer WHERE id=?", (rid,))


def remove_reviewer(rid, keep_decisions=True):
    """Removing a reviewer never silently removes their judgements, because
    those judgements are what the PRISMA counts are built from."""
    n = db.one("SELECT COUNT(*) c FROM screen WHERE reviewer=?", (rid,))
    if not keep_decisions:
        db.exec_("DELETE FROM screen WHERE reviewer=?", (rid,))
    db.exec_("DELETE FROM reviewer WHERE id=?", (rid,))
    return {"decisions": n["c"] if n else 0, "kept": keep_decisions}


# ─────────────────────────────────────────────────────────────────────────
#  Screening
# ─────────────────────────────────────────────────────────────────────────

EXCLUSION_REASONS = [
    "Wrong population", "Wrong intervention", "Wrong comparator", "Wrong outcome",
    "Wrong study design", "Not primary research", "Duplicate report of an included study",
    "Animal or in vitro study", "Language", "Full text unavailable",
    "Insufficient data reported", "Conference abstract only", "Retracted",
]


def queue(project_id=None, stage="title_abstract", reviewer=None, limit=50, blind=True):
    """Records not yet judged by this reviewer at this stage.

    Full-text eligibility is based on the adjudicated title/abstract state,
    not on any single reviewer's raw vote.  A disagreement therefore waits
    for resolution instead of leaking into the next stage.
    """
    clauses = ["r.project_id IS ?", "r.dedup_of IS NULL"]
    args = [project_id]
    if stage == "full_text":
        states = _final_screen_states(project_id, "title_abstract")
        eligible = [rid for rid, st in states.items()
                    if st.get("final") and st.get("decision") in ("include", "maybe")]
        if not eligible:
            return {"records": [], "remaining": 0, "total": 0, "done": 0,
                    "reasons": EXCLUSION_REASONS, "blind": blind}
        marks = ",".join("?" for _ in eligible)
        clauses.append(f"r.id IN ({marks})")
        args.extend(eligible)

    base = " AND ".join(clauses)
    rows = db.query(
        f"SELECT r.* FROM record r WHERE {base} "
        "AND r.id NOT IN (SELECT record_id FROM screen WHERE stage=? AND reviewer=?) "
        "ORDER BY r.year DESC LIMIT ?",
        (*args, stage, reviewer or "", limit))
    total = db.one(f"SELECT COUNT(*) c FROM record r WHERE {base}", tuple(args))
    done = db.one(
        "SELECT COUNT(DISTINCT s.record_id) c FROM screen s JOIN record r ON r.id=s.record_id "
        f"WHERE {base} AND s.stage=? AND s.reviewer=?",
        (*args, stage, reviewer or ""))
    # Outside blind mode the queue carries what the other reviewers said, so a
    # second pass can be a check rather than a repeat. Inside it, that is
    # withheld, which is the entire point of screening twice.
    if not blind:
        others = db.query(
            "SELECT s.record_id, s.decision, v.name, v.initials, v.colour FROM screen s "
            "JOIN reviewer v ON v.id = s.reviewer JOIN record r ON r.id=s.record_id "
            "WHERE r.project_id IS ? AND s.stage=? AND s.reviewer != ?",
            (project_id, stage, reviewer or ""))
        by_rec = {}
        for o in others:
            by_rec.setdefault(o["record_id"], []).append(o)
        for r in rows:
            r["others"] = by_rec.get(r["id"], [])
    return {"records": rows, "remaining": max(0, (total["c"] if total else 0) - (done["c"] if done else 0)),
            "total": total["c"] if total else 0, "done": done["c"] if done else 0,
            "reasons": EXCLUSION_REASONS, "blind": blind}


def decide(record_id, decision, stage="title_abstract", reviewer=None, reason=None):
    if decision not in ("include", "exclude", "maybe"):
        raise ValueError("Decision must be include, exclude, or maybe.")
    reviewer = reviewer or ""
    record = db.one("SELECT project_id FROM record WHERE id=?", (record_id,))
    if not record:
        raise KeyError("Record not found.")
    prior = db.one("SELECT * FROM screen WHERE record_id=? AND stage=? AND reviewer=?",
                   (record_id, stage, reviewer))
    row = {"id": db.new_id("scr_"),
           "record_id": record_id, "stage": stage, "reviewer": reviewer,
           "decision": decision, "reason": reason, "decided_at": time.time()}
    row["id"] = db.upsert("screen", row, ("record_id", "stage", "reviewer"))
    predecessor = db.one("SELECT id FROM screening_event WHERE project_id=? AND record_id=? "
                         "AND stage=? AND reviewer=? ORDER BY created_at DESC LIMIT 1",
                         (record["project_id"], record_id, stage, reviewer))
    db.insert("screening_event", {
        "id": db.new_id("sev_"), "project_id": record["project_id"],
        "record_id": record_id, "stage": stage, "reviewer": reviewer,
        "action": "replace" if prior else "decide", "decision": decision,
        "reason": reason, "predecessor_event_id": (predecessor or {}).get("id"),
        "created_at": time.time(),
    })
    if prior and (prior.get("decision") != decision or prior.get("reason") != reason):
        db.exec_("UPDATE resolution SET superseded_at=? WHERE record_id=? AND stage=? "
                 "AND superseded_at IS NULL", (time.time(), record_id, stage))
    return row


def undo_latest(project_id, stage, reviewer):
    reviewer = reviewer or ""
    row = db.one("SELECT s.*,r.title,r.project_id FROM screen s JOIN record r "
                 "ON r.id=s.record_id WHERE r.project_id IS ? AND s.stage=? "
                 "AND s.reviewer=? ORDER BY s.decided_at DESC LIMIT 1",
                 (project_id, stage, reviewer))
    if not row:
        return None
    predecessor = db.one("SELECT id FROM screening_event WHERE project_id=? AND record_id=? "
                         "AND stage=? AND reviewer=? ORDER BY created_at DESC LIMIT 1",
                         (project_id, row["record_id"], stage, reviewer))
    with db.transaction():
        db.exec_("DELETE FROM screen WHERE id=?", (row["id"],))
        db.insert("screening_event", {
            "id": db.new_id("sev_"), "project_id": project_id,
            "record_id": row["record_id"], "stage": stage, "reviewer": reviewer,
            "action": "undo", "decision": row["decision"], "reason": row.get("reason"),
            "predecessor_event_id": (predecessor or {}).get("id"),
            "created_at": time.time(),
        })
        db.exec_("UPDATE resolution SET superseded_at=? WHERE record_id=? AND stage=? "
                 "AND superseded_at IS NULL", (time.time(), row["record_id"], stage))
    return row


def agreement(project_id=None, stage="title_abstract", a=None, b=None):
    """Cohen's kappa between two reviewers, plus the conflicts to resolve.

    Percentage agreement is reported alongside because people expect it, and
    with a caveat because it is nearly meaningless here: two reviewers who
    exclude 95% of records agree 90% of the time by chance alone.
    """
    revs = reviewers(project_id)
    if len(revs) < 2:
        return {"n_reviewers": len(revs), "reviewers": revs,
                "note": "Kappa needs a second reviewer. Add one above."}
    a = a or revs[0]["id"]
    b = b or revs[1]["id"]
    names = {r["id"]: r for r in revs}
    rows = db.query(
        "SELECT s1.record_id, s1.decision d1, s2.decision d2, s1.reason r1, s2.reason r2 "
        "FROM screen s1 JOIN screen s2 "
        "ON s1.record_id = s2.record_id AND s1.stage = s2.stage "
        "JOIN record r ON r.id=s1.record_id "
        "WHERE r.project_id IS ? AND s1.reviewer=? AND s2.reviewer=? AND s1.stage=?",
        (project_id, a, b, stage))
    if not rows:
        return {"n_reviewers": len(revs), "reviewers": revs, "n_overlap": 0,
                "pair": [names.get(a, {}).get("name"), names.get(b, {}).get("name")],
                "note": "No records have been judged by both reviewers yet."}
    cats = sorted({r["d1"] for r in rows} | {r["d2"] for r in rows})
    n = len(rows)
    obs = sum(1 for r in rows if r["d1"] == r["d2"]) / n
    exp = sum((sum(1 for r in rows if r["d1"] == c) / n) *
              (sum(1 for r in rows if r["d2"] == c) / n) for c in cats)
    k = (obs - exp) / (1 - exp) if exp != 1 else None
    band = None
    if k is not None:
        band = ("poor" if k < 0.2 else "fair" if k < 0.4 else "moderate" if k < 0.6
                else "substantial" if k < 0.8 else "almost perfect")
    conflicts = db.query(
        "SELECT s1.record_id, s1.decision d1, s2.decision d2, r.title, r.year, r.authors, "
        "r.abstract, res.decision resolved, res.rationale "
        "FROM screen s1 JOIN screen s2 "
        "ON s1.record_id = s2.record_id AND s1.stage = s2.stage "
        "JOIN record r ON r.id = s1.record_id "
        "LEFT JOIN resolution res ON res.record_id = s1.record_id AND res.stage = s1.stage "
        "AND res.superseded_at IS NULL "
        "WHERE r.project_id IS ? AND s1.reviewer=? AND s2.reviewer=? AND s1.stage=? "
        "AND s1.decision != s2.decision",
        (project_id, a, b, stage))
    return {"n_reviewers": len(revs), "reviewers": revs,
            "pair": [names.get(a, {}).get("name"), names.get(b, {}).get("name")],
            "pair_ids": [a, b],
            "n_overlap": n, "percent_agreement": round(100 * obs, 1),
            "kappa": None if k is None else round(k, 3), "interpretation": band,
            "conflicts": conflicts,
            "n_unresolved": sum(1 for c in conflicts if not c.get("resolved")),
            "note": ("Report the kappa, the number of conflicts, and how they were "
                     "resolved. All three are PRISMA items.")}


def resolve(record_id, stage, decision, rationale="", by=None):
    """Record an adjudicated decision. It sits alongside the reviewers'
    judgements rather than overwriting them, so the disagreement stays visible
    in the audit trail."""
    votes = db.query("SELECT reviewer,decision,reason,decided_at FROM screen "
                     "WHERE record_id=? AND stage=? ORDER BY reviewer", (record_id, stage))
    vote_sha = hashlib.sha256(json.dumps(votes, sort_keys=True,
                              separators=(",", ":"), default=str).encode()).hexdigest()
    row = {"id": db.new_id("res_"),
           "record_id": record_id, "stage": stage, "decision": decision,
           "rationale": rationale, "resolved_by": by, "resolved_at": time.time(),
           "vote_sha": vote_sha, "superseded_at": None}
    row["id"] = db.upsert("resolution", row, ("record_id", "stage"))
    record = db.one("SELECT project_id FROM record WHERE id=?", (record_id,))
    if record:
        db.insert("screening_event", {
            "id": db.new_id("sev_"), "project_id": record["project_id"],
            "record_id": record_id, "stage": stage, "reviewer": by or "",
            "action": "adjudicate", "decision": decision, "reason": rationale,
            "predecessor_event_id": None, "created_at": time.time(),
        })
    return row


# ─────────────────────────────────────────────────────────────────────────
#  PRISMA
# ─────────────────────────────────────────────────────────────────────────

def _final_screen_states(project_id, stage):
    """One adjudicated state per unique record in a project.

    ``final`` is true only for a resolution or unanimous reviewer votes.
    Disagreements retain a visible ``maybe`` decision for queue/progress
    diagnostics but are not treated as an adjudicated inclusion/exclusion.
    """
    records = db.query("SELECT id FROM record WHERE project_id IS ? AND dedup_of IS NULL",
                       (project_id,))
    ids = {r["id"] for r in records}
    states = {rid: {"decision": None, "reason": None, "final": False} for rid in ids}
    if not ids:
        return states
    votes = db.query(
        "SELECT s.record_id, s.decision, s.reason FROM screen s JOIN record r ON r.id=s.record_id "
        "WHERE r.project_id IS ? AND s.stage=?", (project_id, stage))
    by_record = {}
    for v in votes:
        by_record.setdefault(v["record_id"], []).append(v)
    resolutions = {r["record_id"]: r for r in db.query(
        "SELECT res.* FROM resolution res JOIN record r ON r.id=res.record_id "
        "WHERE r.project_id IS ? AND res.stage=? AND res.superseded_at IS NULL",
        (project_id, stage))}
    for rid in ids:
        if rid in resolutions:
            states[rid] = {"decision": resolutions[rid]["decision"],
                           "reason": None, "final": True}
            continue
        vv = by_record.get(rid, [])
        if not vv:
            continue
        decisions = {v["decision"] for v in vv}
        if len(decisions) == 1:
            decision = next(iter(decisions))
            reasons = {v.get("reason") for v in vv if v.get("reason")}
            states[rid] = {"decision": decision,
                           "reason": next(iter(reasons)) if len(reasons) == 1 else None,
                           "final": True}
        else:
            states[rid] = {"decision": "maybe", "reason": None, "final": False}
    return states


def prisma_counts(project_id=None):
    def c(sql, args=()):
        r = db.one(sql, args)
        return r["c"] if r else 0

    identified_db = c("SELECT COUNT(*) c FROM record WHERE project_id IS ? "
                      "AND source NOT IN ('ctgov','ictrp','ctis','isrctn')", (project_id,))
    identified_reg = c("SELECT COUNT(*) c FROM record WHERE project_id IS ? "
                       "AND source IN ('ctgov','ictrp','ctis','isrctn')", (project_id,))
    dupes = c("SELECT COUNT(*) c FROM record WHERE project_id IS ? AND dedup_of IS NOT NULL",
              (project_id,))
    unique = identified_db + identified_reg - dupes
    ta = _final_screen_states(project_id, "title_abstract")
    ft = _final_screen_states(project_id, "full_text")
    screened = sum(1 for x in ta.values() if x["decision"] is not None)
    excl_ta = sum(1 for x in ta.values() if x.get("final") and x["decision"] == "exclude")
    fulltext = sum(1 for x in ft.values() if x["decision"] is not None)
    excl_ft = sum(1 for x in ft.values() if x.get("final") and x["decision"] == "exclude")
    included = sum(1 for x in ft.values() if x.get("final") and x["decision"] == "include")
    reason_counts = {}
    for x in ft.values():
        if x.get("final") and x["decision"] == "exclude" and x.get("reason"):
            reason_counts[x["reason"]] = reason_counts.get(x["reason"], 0) + 1
    reasons = [{"reason": k, "n": v} for k, v in
               sorted(reason_counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {"kind": "screening",
            "counts": {"identified_db": identified_db, "identified_reg": identified_reg,
                       "duplicates": dupes, "after_dedup": unique,
                       "screened": screened, "excluded_ta": excl_ta,
                       "fulltext": fulltext, "excluded_ft": excl_ft,
                       "included": included},
            "exclusion_reasons": reasons,
            "note": "Every number is derived from project-scoped screening and adjudication "
                    "records, so final-flow counts reflect the decisions actually resolved."}


# ─────────────────────────────────────────────────────────────────────────
#  Risk of bias
# ─────────────────────────────────────────────────────────────────────────

INSTRUMENTS = {
    "rob2": {
        "label": "RoB 2 (randomised trials)",
        "judgements": [("low", "Low"), ("some", "Some concerns"), ("high", "High")],
        "domains": [
            ("D1", "Randomisation process"),
            ("D2", "Deviations from intended interventions"),
            ("D3", "Missing outcome data"),
            ("D4", "Measurement of the outcome"),
            ("D5", "Selection of the reported result"),
        ],
        "rule": "Overall is high if any domain is high, some concerns if any is some.",
    },
    "robins_i": {
        "label": "ROBINS-I (non-randomised studies of interventions)",
        "judgements": [("low", "Low"), ("moderate", "Moderate"), ("serious", "Serious"),
                       ("critical", "Critical"), ("unclear", "No information")],
        "domains": [
            ("D1", "Confounding"), ("D2", "Selection of participants"),
            ("D3", "Classification of interventions"),
            ("D4", "Deviations from intended interventions"),
            ("D5", "Missing data"), ("D6", "Measurement of outcomes"),
            ("D7", "Selection of the reported result"),
        ],
        "rule": "Overall takes the worst domain judgement.",
    },
    "nos": {
        "label": "Newcastle-Ottawa Scale (cohort and case-control)",
        "judgements": [("0", "0 stars"), ("1", "1 star"), ("2", "2 stars")],
        "domains": [("S1", "Representativeness"), ("S2", "Selection of controls"),
                    ("S3", "Ascertainment of exposure"), ("S4", "Outcome not present at start"),
                    ("C1", "Comparability"), ("O1", "Assessment of outcome"),
                    ("O2", "Adequate follow-up length"), ("O3", "Adequacy of follow-up")],
        "rule": "Sum of stars, maximum 9. Seven or above is conventionally good quality.",
    },
    "quadas2": {
        "label": "QUADAS-2 (diagnostic accuracy)",
        "judgements": [("low", "Low"), ("high", "High"), ("unclear", "Unclear")],
        "domains": [("D1", "Patient selection"), ("D2", "Index test"),
                    ("D3", "Reference standard"), ("D4", "Flow and timing"),
                    ("A1", "Applicability: patient selection"),
                    ("A2", "Applicability: index test"),
                    ("A3", "Applicability: reference standard")],
        "rule": "Report risk of bias and applicability separately.",
    },
}


def set_rob(record_id, instrument, domains, overall=None):
    inst = INSTRUMENTS.get(instrument)
    if not inst:
        raise ValueError(f"Unknown instrument {instrument!r}.")
    domains = {str(k): str(v) for k, v in (domains or {}).items()}
    allowed_domains = {k for k, _ in inst["domains"]}
    unknown = sorted(set(domains) - allowed_domains)
    if unknown:
        raise ValueError("Unknown domain(s) for this instrument: " + ", ".join(unknown))
    allowed_values = {str(v) for v, _ in inst["judgements"]}
    invalid = {k: v for k, v in domains.items() if v not in allowed_values}
    if invalid:
        raise ValueError("Invalid risk-of-bias judgement(s): " +
                         ", ".join(f"{k}={v}" for k, v in sorted(invalid.items())))

    # Newcastle-Ottawa awards at most one star in every domain except
    # comparability, which can award two.  Enforce the instrument's own scale
    # rather than allowing every domain to contribute two stars.
    if instrument == "nos":
        for key, value in domains.items():
            limit = 2 if key == "C1" else 1
            if int(value) > limit:
                raise ValueError(f"{key} allows at most {limit} Newcastle-Ottawa star(s).")

    if overall is None:
        vals = list(domains.values())
        complete = allowed_domains.issubset(domains)
        if instrument == "rob2":
            overall = ("incomplete" if not complete else
                       "high" if "high" in vals else
                       "some" if "some" in vals else "low")
        elif instrument == "robins_i":
            if not complete:
                overall = "incomplete"
            elif "critical" in vals:
                overall = "critical"
            elif "serious" in vals:
                overall = "serious"
            elif "moderate" in vals:
                overall = "moderate"
            elif "unclear" in vals:
                overall = "unclear"
            else:
                overall = "low"
        elif instrument == "nos":
            stars = sum(int(v) for v in vals)
            overall = f"{stars}/9" + (" (incomplete)" if not complete else "")
        elif instrument == "quadas2":
            risk_keys = {"D1", "D2", "D3", "D4"}
            appl_keys = {"A1", "A2", "A3"}
            def worst(keys):
                xs = [domains[k] for k in keys if k in domains]
                if not keys.issubset(domains):
                    return "incomplete"
                return "high" if "high" in xs else "unclear" if "unclear" in xs else "low"
            overall = f"RoB: {worst(risk_keys)}; applicability: {worst(appl_keys)}"
    row = {"id": db.new_id("rob_"),
           "record_id": record_id, "instrument": instrument,
           "domains": json.dumps(domains), "overall": overall,
           "updated_at": time.time()}
    row["id"] = db.upsert("rob", row, ("record_id", "instrument"))
    return row


def rob_summary(instrument="rob2", project_id=None):
    inst = INSTRUMENTS.get(instrument, INSTRUMENTS["rob2"])
    rows = db.query(
        "SELECT rb.*, r.title, r.year, r.authors FROM rob rb JOIN record r "
        "ON r.id = rb.record_id WHERE rb.instrument=? AND r.project_id IS ?",
        (instrument, project_id))
    out = []
    for r in rows:
        first = (r["authors"] or "").split(";")[0].strip()
        out.append({"study": f"{first} {r['year'] or ''}".strip() or r["title"][:40],
                    "judgements": json.loads(r["domains"] or "{}"),
                    "overall": r["overall"]})
    return {"kind": "rob", "instrument": instrument,
            "domains": [d[0] for d in inst["domains"]],
            "domain_labels": dict(inst["domains"]),
            "rows": out, "rule": inst["rule"]}


# ─────────────────────────────────────────────────────────────────────────
#  Extraction forms
# ─────────────────────────────────────────────────────────────────────────

DEFAULT_FORMS = {
    "rct": {
        "label": "Randomised trial",
        "fields": [
            P("design", "Design", "select", choices=["Parallel", "Crossover", "Cluster",
                                                     "Factorial"]),
            P("n_total", "Total randomised", "int"),
            P("n_intervention", "n intervention", "int"),
            P("n_control", "n control", "int"),
            P("population", "Population", "textarea"),
            P("intervention", "Intervention", "textarea"),
            P("comparator", "Comparator", "textarea"),
            P("primary_outcome", "Primary outcome", "text"),
            P("followup", "Follow-up duration", "text"),
            P("mean_int", "Mean, intervention", "number"),
            P("sd_int", "SD, intervention", "number"),
            P("mean_ctl", "Mean, control", "number"),
            P("sd_ctl", "SD, control", "number"),
            P("events_int", "Events, intervention", "int"),
            P("events_ctl", "Events, control", "int"),
            P("effect", "Reported effect estimate", "text"),
            P("ci", "Reported interval", "text"),
            P("funding", "Funding source", "text"),
            P("conflicts", "Declared conflicts", "text"),
            P("notes", "Notes", "textarea"),
        ]},
    "observational": {
        "label": "Observational study",
        "fields": [
            P("design", "Design", "select",
              choices=["Cohort", "Case-control", "Cross-sectional", "Case series"]),
            P("n_total", "Total participants", "int"),
            P("exposure", "Exposure", "textarea"),
            P("outcome", "Outcome", "textarea"),
            P("adjusted_for", "Adjusted for", "textarea"),
            P("effect", "Adjusted effect estimate", "text"),
            P("ci", "Interval", "text"),
            P("followup", "Follow-up", "text"),
            P("notes", "Notes", "textarea"),
        ]},
    "diagnostic": {
        "label": "Diagnostic accuracy",
        "fields": [
            P("index_test", "Index test", "text"),
            P("reference", "Reference standard", "text"),
            P("tp", "True positives", "int"), P("fp", "False positives", "int"),
            P("fn", "False negatives", "int"), P("tn", "True negatives", "int"),
            P("threshold", "Threshold", "text"),
            P("setting", "Setting", "text"),
            P("notes", "Notes", "textarea"),
        ]},
}


def save_extraction(record_id, form_id, payload):
    row = {"id": db.new_id("ext_"),
           "record_id": record_id, "form_id": form_id,
           "payload": json.dumps(payload), "updated_at": time.time()}
    row["id"] = db.upsert("extraction", row, ("record_id", "form_id"))
    return row


def extraction_table(form_id="rct", project_id=None):
    rows = db.query(
        "SELECT e.*, r.title, r.year, r.authors FROM extraction e JOIN record r "
        "ON r.id = e.record_id WHERE e.form_id=? AND r.project_id IS ?",
        (form_id, project_id))
    form = DEFAULT_FORMS.get(form_id, DEFAULT_FORMS["rct"])
    out = []
    for r in rows:
        d = json.loads(r["payload"] or "{}")
        first = (r["authors"] or "").split(";")[0].strip()
        d["_study"] = f"{first} {r['year'] or ''}".strip()
        d["_record_id"] = r["record_id"]
        out.append(d)
    return {"form": form_id, "fields": [f["id"] for f in form["fields"]],
            "labels": {f["id"]: f["label"] for f in form["fields"]}, "rows": out}


def to_meta_frame(form_id="rct", project_id=None, measure="SMD"):
    """Turn extracted arm-level data into the columns the meta-analysis expects."""
    import math
    tbl = extraction_table(form_id, project_id)
    rows = []
    for d in tbl["rows"]:
        try:
            if measure in ("SMD", "MD") and d.get("mean_int") is not None:
                n1, n2 = float(d["n_intervention"]), float(d["n_control"])
                m1, m2 = float(d["mean_int"]), float(d["mean_ctl"])
                s1, s2 = float(d["sd_int"]), float(d["sd_ctl"])
                sp = math.sqrt(((n1 - 1) * s1**2 + (n2 - 1) * s2**2) / (n1 + n2 - 2))
                if measure == "MD":
                    y = m1 - m2
                    v = s1**2 / n1 + s2**2 / n2
                else:
                    d_raw = (m1 - m2) / sp
                    J = 1 - 3 / (4 * (n1 + n2 - 2) - 1)
                    y = d_raw * J
                    v = (n1 + n2) / (n1 * n2) + y**2 / (2 * (n1 + n2))
            elif measure in ("OR", "RR") and d.get("events_int") is not None:
                a = float(d["events_int"]); n1 = float(d["n_intervention"])
                c = float(d["events_ctl"]); n2 = float(d["n_control"])
                b, dd = n1 - a, n2 - c
                a, b, c, dd = [max(x, 0.5) for x in (a, b, c, dd)]
                if measure == "OR":
                    y = math.log((a * dd) / (b * c))
                    v = 1 / a + 1 / b + 1 / c + 1 / dd
                else:
                    y = math.log((a / n1) / (c / n2))
                    v = 1 / a - 1 / n1 + 1 / c - 1 / n2
            else:
                continue
            rows.append({"study": d.get("_study", ""), "effect": y,
                         "se": math.sqrt(v), "n": d.get("n_total")})
        except (TypeError, ValueError, ZeroDivisionError, KeyError):
            continue
    return {"measure": measure, "rows": rows, "k": len(rows),
            "note": ("Effects are on the log scale for ratio measures, which is what "
                     "the meta-analysis expects.")}
