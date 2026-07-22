"""Projects: kinds and their derived stage checks."""

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

