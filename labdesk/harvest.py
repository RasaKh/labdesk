"""Literature, trial registry and biological database harvesting.

SOURCE_REGISTRY is the same declarative pattern as the test registry: each
source declares its query fields, its rate limit, and whether it needs a key.
Each declared source now has a client that turns its parameters into recorded
records, and a registry of those clients."""

import json
import os
import re
import time
import urllib.parse

from . import db
from .config import CACHE_DIR, get
from .schema import P, group_registry, index

READY, STUB = "ready", "stub"


def S(id, label, group, base, blurb="", params=None, needs_key=False,
      rate=3, status=STUB, docs=None):
    return {"id": id, "label": label, "group": group, "base": base,
            "blurb": blurb, "params": params or [], "needs_key": needs_key,
            "rate": rate, "status": status, "docs": docs}


COMMON_Q = [
    P("query", "Query", "textarea",
      placeholder="olfactory ensheathing cell AND spinal cord injury",
      help="Field tags and boolean operators are passed through unchanged."),
    P("limit", "Maximum records", "int", default=200, min=1, max=10000),
    P("year_from", "From year", "int"),
    P("year_to", "To year", "int"),
]

SOURCES = [

    S("pubmed", "PubMed", "Literature", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
      status=READY, rate=10,
      blurb="E-utilities esearch then efetch. An API key raises the rate limit from "
            "3 to 10 requests per second.",
      needs_key=False,
      params=COMMON_Q + [
          P("pub_types", "Publication types", "multiselect",
            choices=[("Randomized Controlled Trial", "RCT"),
                     ("Meta-Analysis", "Meta-analysis"),
                     ("Systematic Review", "Systematic review"),
                     ("Clinical Trial", "Clinical trial"),
                     ("Review", "Review"), ("Case Reports", "Case report"),
                     ("Observational Study", "Observational study")]),
          P("species", "Species", "select", default="",
            choices=[("", "Any"), ("humans", "Human"), ("animals", "Animal")]),
          P("language", "Language", "text", placeholder="english"),
          P("has_abstract", "Abstract only", "bool", default=True),
          P("free_full_text", "Free full text only", "bool", default=False),
          P("sort", "Sort", "select", default="relevance",
            choices=[("relevance", "Relevance"), ("pub_date", "Newest first")]),
      ],
      docs="https://www.ncbi.nlm.nih.gov/books/NBK25501/"),

    S("europepmc", "Europe PMC", "Literature",
      "https://www.ebi.ac.uk/europepmc/webservices/rest", status=READY,
      blurb="Wider coverage than PubMed, includes preprints and patents, and returns "
            "citation counts and full text where available.",
      params=COMMON_Q + [
          P("open_access", "Open access only", "bool", default=False),
          P("include_preprints", "Include preprints", "bool", default=True),
          P("sort", "Sort", "select", default="relevance",
            choices=[("relevance", "Relevance"), ("cited", "Most cited"),
                     ("date", "Newest first")])]),

    S("openalex", "OpenAlex", "Literature", "https://api.openalex.org", status=READY,
      blurb="Free, keyless, very large. The best source for bibliometrics, citation "
            "graphs and institution or author disambiguation. Set an email in Settings "
            "to enter the polite pool; without one you will be rate limited.",
      params=COMMON_Q + [
          P("filter", "Raw filter expression", "text",
            placeholder="concepts.id:C71924100,is_oa:true", adv=True),
          P("min_citations", "Minimum citations", "int"),
          P("institution", "Institution", "text", placeholder="ror.org id or name")]),

    S("crossref", "Crossref", "Literature", "https://api.crossref.org", status=READY,
      blurb="Authoritative DOI metadata, reference lists, and the retraction register.",
      params=COMMON_Q + [P("has_references", "With reference lists only", "bool",
                           default=False)]),

    S("semantic_scholar", "Semantic Scholar", "Literature",
      "https://api.semanticscholar.org/graph/v1", needs_key=False,
      blurb="One-line summaries, citation contexts and embeddings for similarity search.",
      params=COMMON_Q + [P("fields", "Fields", "text",
                           default="title,abstract,year,authors,venue,citationCount,tldr")]),

    S("biorxiv", "bioRxiv and medRxiv", "Literature",
      "https://api.biorxiv.org", status=READY,
      blurb="Preprints, with the published-version link once a preprint appears in a "
            "journal.",
      params=[P("server", "Server", "select", default="medrxiv",
                choices=[("biorxiv", "bioRxiv"), ("medrxiv", "medRxiv")]),
              P("days", "Last N days", "int", default=30, min=1, max=3650),
              P("query", "Filter titles containing", "text"),
              P("limit", "Maximum records", "int", default=200)]),

    S("unpaywall", "Unpaywall", "Literature", "https://api.unpaywall.org/v2",
      status=READY, needs_key=True,
      blurb="Resolves a DOI to a legal open-access full text. Needs only an email "
            "address, set in Settings.",
      params=[P("dois", "DOIs", "textarea", placeholder="One per line"),
              P("from_corpus", "Resolve every DOI in the corpus", "bool", default=True)]),

    S("retraction", "Retraction check", "Literature", "https://api.crossref.org",
      status=READY,
      blurb="Checks every DOI in the corpus against Crossref update notices: "
            "retractions, expressions of concern and corrections.",
      params=[P("scope", "Scope", "select", default="corpus",
                choices=[("corpus", "Whole corpus"), ("included", "Included studies only")])]),

    S("ctgov", "ClinicalTrials.gov", "Trial registries",
      "https://clinicaltrials.gov/api/v2", status=READY,
      blurb="API v2. Conditions, interventions, phase, status, enrolment, outcomes "
            "and results where posted.",
      params=[
          P("condition", "Condition", "text", placeholder="spinal cord injury"),
          P("intervention", "Intervention", "text"),
          P("term", "Other terms", "text"),
          P("status", "Status", "multiselect",
            choices=[("RECRUITING", "Recruiting"), ("COMPLETED", "Completed"),
                     ("ACTIVE_NOT_RECRUITING", "Active, not recruiting"),
                     ("TERMINATED", "Terminated"), ("WITHDRAWN", "Withdrawn"),
                     ("NOT_YET_RECRUITING", "Not yet recruiting"),
                     ("UNKNOWN", "Unknown")]),
          P("phase", "Phase", "multiselect",
            choices=[("PHASE1", "1"), ("PHASE2", "2"), ("PHASE3", "3"), ("PHASE4", "4"),
                     ("EARLY_PHASE1", "Early 1"), ("NA", "Not applicable")]),
          P("study_type", "Study type", "select", default="",
            choices=[("", "Any"), ("INTERVENTIONAL", "Interventional"),
                     ("OBSERVATIONAL", "Observational")]),
          P("country", "Country", "text"),
          P("has_results", "With posted results only", "bool", default=False),
          P("limit", "Maximum records", "int", default=200, min=1, max=5000),
      ],
      docs="https://clinicaltrials.gov/data-api/api"),

    S("ictrp", "WHO ICTRP", "Trial registries", "https://trialsearch.who.int",
      blurb="Aggregates national registries not covered by ClinicalTrials.gov. "
            "Needed for a complete search in a systematic review.",
      params=[P("query", "Query", "text"), P("limit", "Maximum records", "int", default=200)]),

    S("ctis", "EU CTIS", "Trial registries", "https://euclinicaltrials.eu",
      blurb="The EU register that replaced EudraCT.",
      params=[P("query", "Query", "text"), P("limit", "Maximum records", "int", default=200)]),

    S("isrctn", "ISRCTN", "Trial registries", "https://www.isrctn.com/api",
      params=[P("query", "Query", "text"), P("limit", "Maximum records", "int", default=200)]),

    S("prospero", "PROSPERO", "Trial registries", "https://www.crd.york.ac.uk/prospero",
      blurb="Check whether your review question is already registered before "
            "committing months to it.",
      params=[P("query", "Query", "text")]),

    S("openfda", "openFDA", "Drugs and safety", "https://api.fda.gov", status=READY,
      blurb="Adverse event reports, drug labels, recalls and device events.",
      params=[P("endpoint", "Endpoint", "select", default="drug/event",
                choices=[("drug/event", "Adverse events (FAERS)"),
                         ("drug/label", "Drug labels"),
                         ("drug/enforcement", "Recalls"),
                         ("device/event", "Device adverse events")]),
              P("search", "Search expression", "text",
                placeholder='patient.drug.medicinalproduct:"metformin"'),
              P("count", "Count field", "text", adv=True,
                placeholder="patient.reaction.reactionmeddrapt.exact"),
              P("limit", "Maximum records", "int", default=100, min=1, max=1000)]),

    S("chembl", "ChEMBL", "Drugs and safety", "https://www.ebi.ac.uk/chembl/api/data",
      params=[P("query", "Molecule or target", "text"),
              P("limit", "Maximum records", "int", default=100)]),

    S("rxnorm", "RxNorm", "Drugs and safety", "https://rxnav.nlm.nih.gov/REST",
      blurb="Drug name normalisation and interaction lookups.",
      params=[P("query", "Drug name", "text")]),

    S("geo", "GEO", "Molecular", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
      blurb="Expression series metadata, for finding reusable datasets.",
      params=[P("query", "Query", "text"), P("limit", "Maximum records", "int", default=100)]),

    S("gwas", "GWAS Catalog", "Molecular", "https://www.ebi.ac.uk/gwas/rest/api",
      params=[P("trait", "Trait", "text"), P("gene", "Gene", "text"),
              P("limit", "Maximum records", "int", default=100)]),

    S("clinvar", "ClinVar", "Molecular", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
      params=[P("query", "Gene or variant", "text"),
              P("limit", "Maximum records", "int", default=100)]),

    S("uniprot", "UniProt", "Molecular", "https://rest.uniprot.org", status=READY,
      params=[P("query", "Query", "text", placeholder="gene:SOX2 AND organism_id:9606"),
              P("limit", "Maximum records", "int", default=100)]),

    S("ensembl", "Ensembl", "Molecular", "https://rest.ensembl.org",
      params=[P("query", "Gene symbol or id", "text"),
              P("species", "Species", "text", default="homo_sapiens")]),

    S("string", "STRING", "Molecular", "https://string-db.org/api",
      blurb="Protein interaction networks for a gene list.",
      params=[P("genes", "Genes", "textarea"),
              P("species", "Taxon id", "int", default=9606),
              P("score", "Minimum score", "number", default=0.7)]),

    S("reactome", "Reactome", "Molecular", "https://reactome.org/ContentService",
      params=[P("genes", "Genes", "textarea"), P("species", "Species", "text",
                                                 default="Homo sapiens")]),

    S("who_gho", "WHO Global Health Observatory", "Population",
      "https://ghoapi.azureedge.net/api",
      params=[P("indicator", "Indicator code", "text"),
              P("country", "Country code", "text")]),

    S("eurostat", "Eurostat", "Population",
      "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data",
      params=[P("dataset", "Dataset code", "text"),
              P("filters", "Filters", "text", adv=True)]),

]


REGISTRY = index(SOURCES)
GROUPS = group_registry(SOURCES)

#  HTTP with a small on-disk cache. Repeated identical queries during a
#  screening session should not re-hit NCBI.
# ─────────────────────────────────────────────────────────────────────────

_last_call = {}


def _throttle(source_id, rate):
    now = time.time()
    gap = 1.0 / max(0.1, rate)
    wait = gap - (now - _last_call.get(source_id, 0))
    if wait > 0:
        time.sleep(wait)
    _last_call[source_id] = time.time()


def _cache_path(url):
    import hashlib
    return os.path.join(CACHE_DIR, hashlib.sha256(url.encode()).hexdigest()[:32] + ".json")


def fetch(url, source_id="generic", rate=3, as_json=True, headers=None, cache=True):
    import requests
    cp = _cache_path(url)
    ttl = float(get("harvest_cache_hours", 24)) * 3600
    if cache and os.path.exists(cp) and time.time() - os.path.getmtime(cp) < ttl:
        with open(cp, "r", encoding="utf-8") as fh:
            return json.load(fh) if as_json else fh.read()
    _throttle(source_id, rate)
    h = {"User-Agent": f"LabDesk/0.1 (mailto:{get('ncbi_email') or 'unknown'})"}
    h.update(headers or {})
    r = requests.get(url, headers=h, timeout=60)
    r.raise_for_status()
    out = r.json() if as_json else r.text
    if cache:
        with open(cp, "w", encoding="utf-8") as fh:
            json.dump(out, fh) if as_json else fh.write(out)
    return out


# ─────────────────────────────────────────────────────────────────────────
#  Clients
# ─────────────────────────────────────────────────────────────────────────

def _rec(source, uid, **kw):
    d = {"source": source, "source_uid": str(uid), "fetched_at": time.time()}
    d.update(kw)
    return d


def pubmed(params, ctl=None):
    base = REGISTRY["pubmed"]["base"]
    key = get("ncbi_api_key", "")
    rate = 10 if key else 3
    terms = [params.get("query") or ""]
    for pt in params.get("pub_types") or []:
        terms.append(f'"{pt}"[Publication Type]')
    if params.get("species") == "humans":
        terms.append("humans[MeSH Terms]")
    elif params.get("species") == "animals":
        terms.append("animals[MeSH Terms] NOT humans[MeSH Terms]")
    if params.get("language"):
        terms.append(f'{params["language"]}[Language]')
    if params.get("has_abstract"):
        terms.append("hasabstract")
    if params.get("free_full_text"):
        terms.append("free full text[sb]")
    yf, yt = params.get("year_from"), params.get("year_to")
    if yf or yt:
        terms.append(f'("{yf or 1800}"[Date - Publication] : "{yt or 3000}"[Date - Publication])')
    q = " AND ".join(t for t in terms if t)
    limit = int(params.get("limit", 200))

    url = (f"{base}/esearch.fcgi?db=pubmed&retmode=json&retmax={min(limit, 10000)}"
           f"&sort={'pub_date' if params.get('sort') == 'pub_date' else 'relevance'}"
           f"&term={urllib.parse.quote(q)}")
    if key:
        url += f"&api_key={key}"
    res = fetch(url, "pubmed", rate)
    ids = res.get("esearchresult", {}).get("idlist", [])
    total = int(res.get("esearchresult", {}).get("count", 0))
    if ctl:
        ctl.log(f"PubMed: {total:,} records match, retrieving {len(ids)}.")

    out = []
    for i in range(0, len(ids), 200):
        if ctl:
            ctl.check()
            ctl.progress(100 * i / max(1, len(ids)), f"{i} of {len(ids)}")
        chunk = ids[i:i + 200]
        u = (f"{base}/efetch.fcgi?db=pubmed&retmode=xml&id={','.join(chunk)}")
        if key:
            u += f"&api_key={key}"
        xml = fetch(u, "pubmed", rate, as_json=False)
        out += _parse_pubmed_xml(xml)
    return {"records": out, "total_available": total, "query_used": q}


def _parse_pubmed_xml(xml):
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    recs = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID") or ""
        title = "".join(art.find(".//ArticleTitle").itertext()) \
            if art.find(".//ArticleTitle") is not None else ""
        abst = " ".join("".join(a.itertext()) for a in art.findall(".//AbstractText"))
        journal = art.findtext(".//Journal/Title") or ""
        year = art.findtext(".//PubDate/Year") or art.findtext(".//PubDate/MedlineDate") or ""
        year = re.findall(r"\d{4}", str(year))
        authors = []
        for a in art.findall(".//Author"):
            ln = a.findtext("LastName") or ""
            ini = a.findtext("Initials") or ""
            if ln:
                authors.append(f"{ln} {ini}".strip())
        doi = ""
        for aid in art.findall(".//ArticleId"):
            if aid.get("IdType") == "doi":
                doi = (aid.text or "").lower()
        ptypes = [p.text for p in art.findall(".//PublicationType") if p.text]
        mesh = [m.text for m in art.findall(".//DescriptorName") if m.text]
        recs.append(_rec("pubmed", pmid, doi=doi, title=title, abstract=abst,
                         authors="; ".join(authors), journal=journal,
                         year=int(year[0]) if year else None,
                         pub_types="; ".join(ptypes),
                         meta=json.dumps({"mesh": mesh, "pmid": pmid})))
    return recs


def europepmc(params, ctl=None):
    base = REGISTRY["europepmc"]["base"]
    q = params.get("query") or ""
    if params.get("open_access"):
        q += " AND OPEN_ACCESS:y"
    if not params.get("include_preprints", True):
        q += " AND NOT SRC:PPR"
    yf, yt = params.get("year_from"), params.get("year_to")
    if yf or yt:
        q += f" AND PUB_YEAR:[{yf or 1800} TO {yt or 3000}]"
    limit = int(params.get("limit", 200))
    sort = {"cited": "CITED desc", "date": "P_PDATE_D desc"}.get(params.get("sort"), "")
    out, cursor = [], "*"
    while len(out) < limit:
        u = (f"{base}/search?query={urllib.parse.quote(q)}&format=json&pageSize=100"
             f"&cursorMark={urllib.parse.quote(cursor)}&resultType=core")
        if sort:
            u += f"&sort={urllib.parse.quote(sort)}"
        res = fetch(u, "europepmc", 5)
        hits = res.get("resultList", {}).get("result", [])
        if not hits:
            break
        for h in hits:
            out.append(_rec("europepmc", h.get("id", ""),
                            doi=(h.get("doi") or "").lower(),
                            title=h.get("title", ""),
                            abstract=h.get("abstractText", ""),
                            authors=h.get("authorString", ""),
                            journal=h.get("journalTitle", "") or h.get("bookOrReportDetails", ""),
                            year=int(h["pubYear"]) if h.get("pubYear", "").isdigit() else None,
                            pub_types="; ".join(h.get("pubTypeList", {}).get("pubType", [])),
                            oa_url=h.get("fullTextUrlList", {}).get("fullTextUrl", [{}])[0].get("url", "")
                            if h.get("fullTextUrlList") else "",
                            meta=json.dumps({"citations": h.get("citedByCount"),
                                             "source": h.get("source")})))
        nc = res.get("nextCursorMark")
        if not nc or nc == cursor:
            break
        cursor = nc
        if ctl:
            ctl.check()
            ctl.progress(100 * len(out) / limit, f"{len(out)} of {limit}")
    return {"records": out[:limit], "total_available": res.get("hitCount", len(out))}


def openalex(params, ctl=None):
    base = REGISTRY["openalex"]["base"]
    filters = []
    if params.get("year_from") or params.get("year_to"):
        filters.append(f"from_publication_date:{params.get('year_from') or 1800}-01-01")
        if params.get("year_to"):
            filters.append(f"to_publication_date:{params['year_to']}-12-31")
    if params.get("min_citations"):
        filters.append(f"cited_by_count:>{int(params['min_citations'])-1}")
    if params.get("filter"):
        filters.append(params["filter"])
    limit = int(params.get("limit", 200))
    out, cursor = [], "*"
    while len(out) < limit:
        u = (f"{base}/works?search={urllib.parse.quote(params.get('query') or '')}"
             f"&per-page=100&cursor={urllib.parse.quote(cursor)}")
        if filters:
            u += "&filter=" + urllib.parse.quote(",".join(filters))
        if get("ncbi_email"):
            u += f"&mailto={get('ncbi_email')}"
        res = fetch(u, "openalex", 8 if get("ncbi_email") else 1)
        hits = res.get("results", [])
        if not hits:
            break
        for h in hits:
            inv = h.get("abstract_inverted_index") or {}
            abstract = ""
            if inv:
                pos = {}
                for word, idxs in inv.items():
                    for i in idxs:
                        pos[i] = word
                abstract = " ".join(pos[k] for k in sorted(pos))
            out.append(_rec("openalex", h.get("id", "").rsplit("/", 1)[-1],
                            doi=(h.get("doi") or "").replace("https://doi.org/", "").lower(),
                            title=h.get("title") or "",
                            abstract=abstract,
                            authors="; ".join(a["author"]["display_name"]
                                              for a in h.get("authorships", [])[:30]),
                            journal=(h.get("primary_location") or {}).get("source", {})
                            .get("display_name", "") if h.get("primary_location") else "",
                            year=h.get("publication_year"),
                            pub_types=h.get("type", ""),
                            oa_url=(h.get("best_oa_location") or {}).get("pdf_url", "") or "",
                            meta=json.dumps({"citations": h.get("cited_by_count"),
                                             "concepts": [c["display_name"]
                                                          for c in h.get("concepts", [])[:8]]})))
        cursor = res.get("meta", {}).get("next_cursor")
        if not cursor:
            break
        if ctl:
            ctl.check()
            ctl.progress(100 * len(out) / limit, f"{len(out)} of {limit}")
    return {"records": out[:limit]}


def crossref(params, ctl=None):
    base = REGISTRY["crossref"]["base"]
    limit = int(params.get("limit", 200))
    u = (f"{base}/works?query={urllib.parse.quote(params.get('query') or '')}"
         f"&rows={min(limit, 1000)}")
    if params.get("year_from"):
        u += f"&filter=from-pub-date:{params['year_from']}-01-01"
    res = fetch(u, "crossref", 5)
    out = []
    for it in res.get("message", {}).get("items", []):
        yr = None
        try:
            yr = it["issued"]["date-parts"][0][0]
        except Exception:
            pass
        out.append(_rec("crossref", it.get("DOI", ""), doi=(it.get("DOI") or "").lower(),
                        title=" ".join(it.get("title") or []),
                        abstract=re.sub("<[^>]+>", "", it.get("abstract", "") or ""),
                        authors="; ".join(f"{a.get('family','')} {a.get('given','')[:1]}"
                                          for a in it.get("author", [])[:30]),
                        journal=" ".join(it.get("container-title") or []),
                        year=yr, pub_types=it.get("type", ""),
                        retracted=1 if it.get("update-to") else 0,
                        meta=json.dumps({"citations": it.get("is-referenced-by-count")})))
    return {"records": out}


def biorxiv(params, ctl=None):
    server = params.get("server", "medrxiv")
    days = int(params.get("days", 30))
    u = f"https://api.biorxiv.org/details/{server}/{days}d"
    res = fetch(u, "biorxiv", 2)
    filt = (params.get("query") or "").lower()
    out = []
    for it in res.get("collection", []):
        if filt and filt not in (it.get("title", "") + it.get("abstract", "")).lower():
            continue
        yr = (it.get("date") or "")[:4]
        out.append(_rec(server, it.get("doi", ""), doi=(it.get("doi") or "").lower(),
                        title=it.get("title", ""), abstract=it.get("abstract", ""),
                        authors=it.get("authors", ""), journal=f"{server} preprint",
                        year=int(yr) if yr.isdigit() else None,
                        pub_types="Preprint",
                        meta=json.dumps({"published": it.get("published")})))
    return {"records": out[:int(params.get("limit", 200))]}


def ctgov(params, ctl=None):
    base = REGISTRY["ctgov"]["base"]
    q = []
    if params.get("condition"):
        q.append(f"query.cond={urllib.parse.quote(params['condition'])}")
    if params.get("intervention"):
        q.append(f"query.intr={urllib.parse.quote(params['intervention'])}")
    if params.get("term"):
        q.append(f"query.term={urllib.parse.quote(params['term'])}")
    if params.get("status"):
        q.append("filter.overallStatus=" + ",".join(params["status"]))
    if params.get("country"):
        q.append(f"query.locn={urllib.parse.quote(params['country'])}")
    fields = ("NCTId|BriefTitle|OverallStatus|Phase|StudyType|EnrollmentCount|"
              "Condition|InterventionName|StartDate|CompletionDate|LeadSponsorName|"
              "PrimaryOutcomeMeasure|LocationCountry|HasResults|BriefSummary")
    limit = int(params.get("limit", 200))
    out, token = [], None
    while len(out) < limit:
        u = f"{base}/studies?{'&'.join(q)}&pageSize=100&fields={urllib.parse.quote(fields)}"
        if token:
            u += f"&pageToken={token}"
        res = fetch(u, "ctgov", 5)
        studies = res.get("studies", [])
        if not studies:
            break
        for s in studies:
            p = s.get("protocolSection", {})
            idm = p.get("identificationModule", {})
            st = p.get("statusModule", {})
            des = p.get("designModule", {})
            phase = "; ".join(des.get("phases", []) or [])
            if params.get("phase") and not any(ph in (des.get("phases") or [])
                                               for ph in params["phase"]):
                continue
            if params.get("study_type") and des.get("studyType") != params["study_type"]:
                continue
            if params.get("has_results") and not s.get("hasResults"):
                continue
            out.append(_rec("ctgov", idm.get("nctId", ""),
                            title=idm.get("briefTitle", ""),
                            abstract=(p.get("descriptionModule", {}) or {}).get("briefSummary", ""),
                            authors=(p.get("sponsorCollaboratorsModule", {}) or {})
                            .get("leadSponsor", {}).get("name", ""),
                            journal="ClinicalTrials.gov",
                            year=int((st.get("startDateStruct", {}).get("date") or "0000")[:4])
                            if (st.get("startDateStruct", {}).get("date") or "")[:4].isdigit() else None,
                            pub_types=des.get("studyType", ""),
                            meta=json.dumps({
                                "status": st.get("overallStatus"),
                                "phase": phase,
                                "enrollment": (des.get("enrollmentInfo") or {}).get("count"),
                                "conditions": (p.get("conditionsModule", {}) or {}).get("conditions", []),
                                "has_results": s.get("hasResults", False),
                            })))
        token = res.get("nextPageToken")
        if not token:
            break
        if ctl:
            ctl.check()
            ctl.progress(100 * len(out) / limit, f"{len(out)} trials")
    return {"records": out[:limit]}


def openfda(params, ctl=None):
    base = REGISTRY["openfda"]["base"]
    ep = params.get("endpoint", "drug/event")
    u = f"{base}/{ep}.json?limit={int(params.get('limit', 100))}"
    if params.get("search"):
        u += f"&search={urllib.parse.quote(params['search'])}"
    if params.get("count"):
        u += f"&count={urllib.parse.quote(params['count'])}"
    res = fetch(u, "openfda", 4)
    if params.get("count"):
        return {"counts": res.get("results", []), "records": []}
    out = []
    for i, r in enumerate(res.get("results", [])):
        out.append(_rec("openfda", r.get("safetyreportid", i),
                        title=ep, abstract=json.dumps(r)[:2000],
                        meta=json.dumps({"endpoint": ep})))
    return {"records": out}


def uniprot(params, ctl=None):
    u = (f"https://rest.uniprot.org/uniprotkb/search?query="
         f"{urllib.parse.quote(params.get('query') or '')}&format=json"
         f"&size={min(int(params.get('limit', 100)), 500)}")
    res = fetch(u, "uniprot", 5)
    out = []
    for r in res.get("results", []):
        out.append(_rec("uniprot", r.get("primaryAccession", ""),
                        title=(r.get("proteinDescription", {}).get("recommendedName", {})
                               .get("fullName", {}) or {}).get("value", ""),
                        abstract="; ".join(c.get("texts", [{}])[0].get("value", "")
                                           for c in r.get("comments", [])[:3]),
                        meta=json.dumps({"genes": [g.get("geneName", {}).get("value")
                                                   for g in r.get("genes", [])]})))
    return {"records": out}


def unpaywall(params, ctl=None):
    email = get("ncbi_email")
    if not email:
        raise ValueError("Unpaywall needs an email address. Set it in Settings.")
    dois = []
    project_id = params.get("_project_id")
    if params.get("from_corpus", True):
        dois = [r["doi"] for r in db.query(
            "SELECT DISTINCT doi FROM record WHERE project_id IS ? "
            "AND doi IS NOT NULL AND doi != '' AND (oa_url IS NULL OR oa_url = '')",
            (project_id,))]
    for line in str(params.get("dois") or "").splitlines():
        if line.strip():
            dois.append(line.strip().lower())
    found = 0
    for i, doi in enumerate(dois):
        if ctl:
            ctl.check()
            ctl.progress(100 * i / max(1, len(dois)), f"{i} of {len(dois)} DOIs")
        try:
            res = fetch(f"https://api.unpaywall.org/v2/{doi}?email={email}", "unpaywall", 8)
        except Exception:
            continue
        loc = res.get("best_oa_location") or {}
        url = loc.get("url_for_pdf") or loc.get("url") or ""
        if url:
            found += 1
            db.exec_("UPDATE record SET oa_url=? WHERE doi=? AND project_id IS ?",
                     (url, doi, project_id))
    return {"records": [], "resolved": found, "checked": len(dois)}


def retraction(params, ctl=None):
    scope = params.get("scope", "corpus")
    project_id = params.get("_project_id")
    sql = "SELECT id, doi FROM record WHERE project_id IS ? AND doi IS NOT NULL AND doi != ''"
    rows = db.query(sql, (project_id,))
    if scope == "included":
        from . import screening
        states = screening._final_screen_states(project_id, "full_text")
        included = {rid for rid, st in states.items()
                    if st.get("final") and st.get("decision") == "include"}
        rows = [r for r in rows if r["id"] in included]
    flagged = []
    for i, r in enumerate(rows):
        if ctl:
            ctl.check()
            ctl.progress(100 * i / max(1, len(rows)), f"{i} of {len(rows)} DOIs")
        try:
            res = fetch(f"https://api.crossref.org/works/{urllib.parse.quote(r['doi'])}",
                        "crossref", 5)
        except Exception:
            continue
        msg = res.get("message", {})
        updates = msg.get("update-to") or []
        kinds = {u.get("type", "").lower() for u in updates}
        if kinds & {"retraction", "withdrawal", "removal"}:
            db.exec_("UPDATE record SET retracted=1 WHERE id=?", (r["id"],))
            flagged.append({"doi": r["doi"], "type": "retraction"})
        elif "expression_of_concern" in kinds:
            db.exec_("UPDATE record SET retracted=2 WHERE id=?", (r["id"],))
            flagged.append({"doi": r["doi"], "type": "expression of concern"})
    return {"records": [], "flagged": flagged, "checked": len(rows),
            "message": (f"{len(flagged)} of {len(rows)} records carry a retraction or "
                        "expression of concern." if flagged else
                        f"No retractions found among {len(rows)} records.")}


CLIENTS = {
    "pubmed": pubmed, "europepmc": europepmc, "openalex": openalex,
    "crossref": crossref, "biorxiv": biorxiv, "ctgov": ctgov,
    "openfda": openfda, "uniprot": uniprot,
    "unpaywall": unpaywall, "retraction": retraction,
}
