"""Literature, trial registry and biological database harvesting.

SOURCE_REGISTRY is the same declarative pattern as the test registry: each
source declares its query fields, its rate limit, and whether it needs a key.
The full source table is now declared across literature, trial registries,
drug and safety, molecular, and population groups."""


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

]


REGISTRY = index(SOURCES)
GROUPS = group_registry(SOURCES)
