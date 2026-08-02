"""Evidence synthesis: deduplication."""

import re

from . import db

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
