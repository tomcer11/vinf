"""
Search in the tree index (index/index.json.gz, built by indexer.py)

Query language:
  free words              anthracnose       ranked over all fields (FIELD_WEIGHTS)
  field:word              pest:aphid        the word must be in that field
  field:"two words"       pest:"powdery mildew"
  zone:5-8                USDA hardiness: the plant survives in all zones 5 to 8
  status:EN               IUCN conservation status, also status:EN,CR
  kind:species            or kind:genus
  source:gardenia         only documents with gardenia plants mapped to them
  height:30-              TSO height in metres: 30-   -5   10-20
  toxic:dogs              poisonous according to gardenia (dogs, cats, horses, humans)

  fields: title, name, synonym, cultivar, taxonomy (family, genus), distribution
          (country), habitat, pest, morphology, garden (exposure, soil, tolerance), text

Usage:
  python search.py "Picea abies"                  # card of the species + ranked list
  python search.py "Potentilla fruticosa"         # a synonym: card of Dasiphora fruticosa
  python search.py "pest:leafhopper" --idf smooth
  python search.py "zone:5-8 habitat:mountain" -k 20
  python search.py "habitat:rainforest" --compare # the query with every idf method
  python search.py                                # interactive
"""

import argparse
import json
import re
import shlex
import sys
from dataclasses import dataclass, field

from indexer import FIELD_WEIGHTS, IDF_METHODS, INDEX_PATH, MODELS, TREES_PATH, Index, \
    doc_fields, normalize, tokenize
from extractor import sentences

FIELD_ALIASES = {
    "title": "title", "name": "name", "synonym": "synonyms", "synonyms": "synonyms",
    "cultivar": "cultivars", "cultivars": "cultivars",
    "taxonomy": "taxonomy", "family": "taxonomy", "genus": "taxonomy",
    "distribution": "distribution", "country": "distribution", "native": "distribution",
    "habitat": "habitat", "pest": "pests", "pests": "pests", "disease": "pests",
    "morphology": "morphology", "garden": "garden",
    "tolerance": "garden", "soil": "garden", "exposure": "garden", "text": "text",
}
FILTERS = {"zone", "status", "kind", "source", "height", "toxic"}

RANGE_RE = re.compile(r"^(\d+(?:\.\d+)?)?\s*-\s*(\d+(?:\.\d+)?)?$|^(\d+(?:\.\d+)?)$")


@dataclass
class Query:
    free: list[str] = field(default_factory=list)                     # stemmed terms
    fielded: dict[str, list[str]] = field(default_factory=dict)       # field -> required terms
    filters: dict[str, str] = field(default_factory=dict)
    text: str = ""                                                    # free words as typed

    def terms_by_field(self) -> dict[str, list[str]]:
        terms = {f: list(self.free) for f in FIELD_WEIGHTS} if self.free else {}
        for f, words in self.fielded.items():
            terms.setdefault(f, []).extend(words)
        return terms


def parse_query(raw: str) -> Query:
    query = Query()
    try:
        parts = shlex.split(raw)
    except ValueError:
        parts = raw.split()

    free_words = []
    for part in parts:
        name, sep, value = part.partition(":")
        name = name.lower()
        if sep and name in FILTERS:
            query.filters[name] = value
        elif sep and name in FIELD_ALIASES:
            words = tokenize(value)
            if words:
                query.fielded.setdefault(FIELD_ALIASES[name], []).extend(words)
        else:
            free_words.append(part)
    query.text = " ".join(free_words)
    query.free = tokenize(query.text)
    return query


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
def parse_range(value: str) -> tuple[float | None, float | None] | None:
    m = RANGE_RE.match(value.strip())
    if not m:
        return None
    if m.group(3):
        v = float(m.group(3))
        return v, v
    low = float(m.group(1)) if m.group(1) else None
    high = float(m.group(2)) if m.group(2) else None
    return low, high


def zone_covers(zones: dict | None, low: float, high: float) -> bool:
    """The plant survives in every zone low..high. A single TSO value says
    only how cold the plant tolerates ('hardy to zone 4'), so its upper end is open."""
    if not zones:
        return False
    if zones["min"] > low:
        return False
    return zones["max"] is None or zones["max"] >= high


def passes(doc: dict, filters: dict[str, str]) -> bool:
    for name, value in filters.items():
        value = value.strip()
        if name == "zone":
            rng = parse_range(value)
            if not rng or not zone_covers(doc["zones"], rng[0] or 1, rng[1] or rng[0] or 13):
                return False
        elif name == "status":
            if (doc.get("conservation") or "").upper() not in {v.upper() for v in value.split(",")}:
                return False
        elif name == "kind":
            if doc["kind"] != value.lower():
                return False
        elif name == "source":
            if value.lower() == "gardenia" and not doc["gardenia"]:
                return False
        elif name == "toxic":
            if value.lower() not in doc.get("toxic_to", []):
                return False
        elif name == "height":
            rng = parse_range(value)
            height = doc.get("height_m")
            if not rng or height is None:
                return False
            if (rng[0] is not None and height < rng[0]) or (rng[1] is not None and height > rng[1]):
                return False
    return True


def zone_order(doc: dict, filters: dict[str, str]) -> tuple:
    """Order for queries without words: exact zone range first, then the
    narrowest range that covers the query, open TSO values last."""
    rng = parse_range(filters.get("zone", "")) if "zone" in filters else None
    zones = doc.get("zones")
    if not rng or not zones:
        return (1, 0, doc["title"])
    if zones["max"] is None:
        return (1, rng[0] - zones["min"], doc["title"])
    return (0, (zones["max"] - zones["min"]) - (rng[1] - rng[0]), doc["title"])


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def search(index: Index, query: Query, idf: str = "classic", model: str = "tfidf",
           k: int = 10) -> tuple[list[tuple[int, float]], int]:
    """Ranked (doc_id, score) list and the number of all matching documents."""
    candidates = None
    for f, words in query.fielded.items():
        for word in words:
            docs = index.docs_with(f, word)
            candidates = docs if candidates is None else candidates & docs

    scores = index.score(query.terms_by_field(), idf, model)
    if candidates is None:
        # without field:word terms a document needs at least one free word;
        # next to field:word terms the free words only change the order
        candidates = set(scores) if query.free else set(range(index.n_docs))

    hits = [d for d in candidates if passes(index.docs[d], query.filters)]
    if query.free or query.fielded:
        ranked = sorted(((d, scores.get(d, 0.0)) for d in hits), key=lambda x: (-x[1], index.docs[x[0]]["title"]))
    else:
        ranked = [(d, 0.0) for d in sorted(hits, key=lambda d: zone_order(index.docs[d], query.filters))]
    return ranked[:k], len(hits)


def load_documents(ids: set[int]) -> dict[int, dict]:
    """Full documents of trees.jsonl (line number = document id)."""
    found = {}
    with TREES_PATH.open(encoding="utf-8") as f:
        for doc_id, line in enumerate(f):
            if doc_id in ids:
                found[doc_id] = json.loads(line)
                if len(found) == len(ids):
                    break
    return found


def snippet(doc: dict, query: Query, width: int = 220) -> str:
    """Sentence of the first matching field that contains a query term; the
    longest one, so that a real sentence wins over the bare pest name "aphid"."""
    texts = doc_fields(doc)
    order = list(query.fielded) + ["pests", "habitat", "distribution", "title", "name", "synonyms",
                                   "garden", "morphology", "text"]
    for f in dict.fromkeys(order):
        wanted = set(query.fielded.get(f, [])) | set(query.free)
        if not wanted:
            continue
        field_sentences = sentences(texts.get(f, ""))
        matching = [s for s in field_sentences if wanted & set(tokenize(s))]
        if matching:
            best = max(matching, key=lambda s: len(tokenize(s)))
            if len(tokenize(best)) < 2:
                # only the tag "mountain" (added for an altitude or a range
                # name) matched: show the habitat text it was derived from
                best = max(field_sentences, key=lambda s: len(tokenize(s)))
            best = " ".join(best.split())
            return f"[{f}] " + (best if len(best) <= width else best[:width - 3] + "...")
    return ""


def describe(doc: dict) -> str:
    parts = [doc["kind"]]
    if doc.get("common"):
        parts.append(", ".join(doc["common"][:2]))
    zones = doc.get("zones")
    if zones:
        parts.append(f"USDA {zones['min']}" + (f"-{zones['max']}" if zones["max"] is not None else "+"))
    if doc.get("conservation"):
        parts.append(f"IUCN {doc['conservation']}")
    parts.append(f"TSO + {doc['gardenia']} gardenia" if doc["gardenia"] else "TSO")
    return " | ".join(parts)


def print_results(index: Index, query: Query, ranked, total: int, idf: str, model: str):
    print(f"\n{total} documents match  (model {model}, idf {idf})")
    docs = load_documents({d for d, _ in ranked})
    for rank, (doc_id, score) in enumerate(ranked, 1):
        info = index.docs[doc_id]
        print(f"{rank:>3}. {score:7.3f}  {info['title']}  ({describe(info)})")
        print(f"            {info['url']}")
        text = snippet(docs[doc_id], query) if doc_id in docs else ""
        if text:
            print(f"            {text}")


def find_species(index: Index, query: Query) -> tuple[int, str] | None:
    """(document, how) whose scientific name, synonym or common name is
    exactly the query: "Potentilla fruticosa" is a synonym of Dasiphora fruticosa."""
    if not query.text or query.fielded:
        return None
    def same(name):
        return " ".join(normalize(name).split()) == wanted
    wanted = " ".join(normalize(query.text).split())
    for info in index.docs:
        if same(info["title"]):
            return info["id"], "name"
    for info in index.docs:
        if info["kind"] == "species" and any(same(s) for s in info.get("synonyms", [])):
            return info["id"], "synonym"
    for info in index.docs:
        if info["kind"] == "species" and any(same(c) for c in info.get("common", [])):
            return info["id"], "common name"
    return None


def print_card(doc: dict):
    """All properties of one tree, from TSO and the gardenia plants mapped to it."""
    def line(label, value):
        if value:
            print(f"  {label:<22}{value}")

    plants = doc.get("gardenia", [])
    print("=" * 78)
    print(f"  {doc['title']}   {doc['url']}")
    print("=" * 78)
    line("Family / genus", " / ".join(x for x in (doc.get("family"), doc.get("genus")) if x))
    line("Common names", ", ".join(doc.get("common_names", [])[:8]))
    tso_synonyms = doc.get("synonym_names", [])
    line("Synonyms (TSO)", f"{len(tso_synonyms)}: " + "; ".join(tso_synonyms[:6])
         + (" ..." if len(tso_synonyms) > 6 else "") if tso_synonyms else "")
    gardenia_synonyms = list(dict.fromkeys(n for p in plants for n in p.get("scientific_synonyms") or []))
    line("Synonyms (gardenia)", "; ".join(gardenia_synonyms[:6]))
    line("Distribution", ", ".join(doc.get("countries", [])) or doc.get("distribution", "")[:300])
    line("Habitat", (doc.get("habitat") or doc.get("habitat_from_text") or "")[:300])
    if doc.get("altitude"):
        line("Altitude", f"{doc['altitude']['min_m']}-{doc['altitude']['max_m']} m")
    line("Mountain habitat", "yes (" + ", ".join(doc.get("mountain_terms", [])) + ")"
         if doc.get("mountain") else "no")
    line("Morphology", doc.get("description", "")[:300].replace("\n", " "))
    if doc.get("height"):
        line("Height (TSO)", f"{doc['height']['min_m']}-{doc['height']['max_m']} m")
    line("Life form", ", ".join(doc.get("life_form", []) + doc.get("leaf_habit", [])))
    line("USDA zone (TSO)", (doc.get("usda") or {}).get("raw"))
    line("USDA zone (gardenia)", ", ".join(sorted({p["hardiness"] for p in plants if p.get("hardiness")})))
    line("RHS rating", doc.get("rhs"))
    line("Conservation", doc.get("conservation_status"))
    line("Editorial note", doc.get("editorial_note", "")[:200])
    line("Pests and diseases", ", ".join(doc.get("all_pests", [])))
    evidence = {}                     # one sentence per pest, TSO first, then gardenia
    for source in [doc] + plants:
        for pest, ev in (source.get("pest_evidence") or {}).items():
            evidence.setdefault(pest, ev[0])
    for pest, sentence in list(evidence.items())[:4]:
        line(f"  - {pest}", sentence[:200])
    if plants:
        first = next((p for p in plants if p["match"] in ("species", "synonym")), plants[0])
        line("Exposure", ", ".join(first.get("exposure") or []))
        line("Soil", ", ".join((first.get("soil_type") or []) + (first.get("soil_ph") or [])))
        line("Tolerances", ", ".join(first.get("tolerances") or []))
        line("Attracts", ", ".join(first.get("attracts") or []))
        line("Toxic to dogs", first.get("toxic_dogs"))
        line("gardenia plants", f"{len(plants)}: " + "; ".join(p["title"] for p in plants[:6])
             + (" ..." if len(plants) > 6 else ""))


def compare(index: Index, query: Query, model: str, k: int):
    """The same query ranked with every idf method, side by side."""
    # free words: shown for the article text, the field where df is largest
    shown = [("text", w) for w in dict.fromkeys(query.free)]
    shown += [(f, w) for f, words in query.fielded.items() for w in dict.fromkeys(words)]
    print(f"\nidf of the query terms (N = {index.n_docs})")
    for f, word in shown:
        df = index.df(f, word)
        values = "  ".join(f"{m}={index.idf(f, word, m):.3f}" for m in IDF_METHODS)
        print(f"  {f + ':' + word:<22} df={df:<5} {values}")
    rankings = {}
    for method in IDF_METHODS:
        ranked, total = search(index, query, method, model, k)
        rankings[method] = [d for d, _ in ranked]
    width = 34
    print(f"\nTop {k} ({model}, {total} matching documents)")
    print("rank  " + "".join(m.ljust(width) for m in IDF_METHODS))
    for i in range(k):
        row = []
        for method in IDF_METHODS:
            ids = rankings[method]
            row.append((index.docs[ids[i]]["title"][:width - 2] if i < len(ids) else "").ljust(width))
        print(f"{i + 1:>4}  " + "".join(row))
    base = set(rankings["classic"])
    for method in IDF_METHODS[1:]:
        same = len(base & set(rankings[method]))
        print(f"  classic vs {method}: {same}/{k} documents in common")


def run_query(index: Index, raw: str, idf: str, model: str, k: int, do_compare: bool):
    query = parse_query(raw)
    print(f"\nquery: {raw!r} -> free={query.free} fields={query.fielded} filters={query.filters}")
    if do_compare:
        compare(index, query, model, k)
        return
    found = find_species(index, query)
    if found is not None:
        doc_id, how = found
        if how != "name":
            print(f"\n'{query.text}' is a {how} of {index.docs[doc_id]['title']}")
        print_card(load_documents({doc_id})[doc_id])
    ranked, total = search(index, query, idf, model, k)
    print_results(index, query, ranked, total, idf, model)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Search the tree index")
    parser.add_argument("query", nargs="?", help="query; without it the search is interactive")
    parser.add_argument("--idf", choices=IDF_METHODS, default="classic")
    parser.add_argument("--model", choices=MODELS, default="tfidf")
    parser.add_argument("-k", type=int, default=10, help="number of results")
    parser.add_argument("--compare", action="store_true", help="rank with every idf method")
    args = parser.parse_args()

    index = Index.load(INDEX_PATH)
    if args.query:
        run_query(index, args.query, args.idf, args.model, args.k, args.compare)
    else:
        print("Empty line ends. Example: pest:aphid zone:5-8")
        while True:
            try:
                raw = input("\nquery> ").strip()
            except EOFError:
                break
            if not raw:
                break
            run_query(index, raw, args.idf, args.model, args.k, args.compare)
