"""
Own inverted index over the tree documents, with several ways to compute idf

Document = one TSO page (species or genus) together with the gardenia plants
mapped to it (data/trees.jsonl, written by mapping.py). Every document is split
into fields (name, synonyms, habitat, pests ...). Each field has its own inverted index

    term -> [[doc_id, tf], ...]        tf = how many times the term is in the field

idf, N = number of documents, df = number of documents whose field has the term:
    classic        idf = log10(N / df)
    smooth         idf = log10(1 + N / df)
    probabilistic  idf = max(0, log10((N - df + 0.5) / (df + 0.5)))   (Robertson / Sparck Jones)

ranking of document d for query q, summed over the queried fields f with
the weights FIELD_WEIGHTS:
    tfidf   w(t, d) = (1 + log10 tf) * idf(t)
            score(d) = sum_f weight_f * cos(q_f, d_f)
    bm25    score(d) = sum_f weight_f * sum_t idf(t) * tf * (k1 + 1)
                                       / (tf + k1 * (1 - b + b * len_f(d) / avglen_f))

Output: index/index.json.gz   documents, and per field: postings, document
                              lengths and vector norms for every idf method

Usage:
  python indexer.py             # build the index from data/trees.jsonl
"""

import gzip
import json
import math
import re
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

TREES_PATH = Path("./data/trees.jsonl")
INDEX_DIR = Path("./index")
INDEX_PATH = INDEX_DIR / "index.json.gz"

IDF_METHODS = ("classic", "smooth", "probabilistic")
MODELS = ("tfidf", "bm25")
BM25_K1 = 1.2
BM25_B = 0.75

# weight of a field when the query is not limited to one field
FIELD_WEIGHTS = {
    "title": 5.0,
    "name": 3.0,
    "synonyms": 3.0,
    "cultivars": 1.0,
    "taxonomy": 2.0,
    "distribution": 1.5,
    "habitat": 1.5,
    "pests": 2.0,
    "morphology": 1.0,
    "garden": 1.0,
    "text": 0.5,
}

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------
TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = set("""
a about above after again against all also although am an and any are as at be because been
before being below between both but by can could did do does doing down during each either
etc few for from further had has have having he her here hers him his how however i if in into
is it its itself just may might more most much must my no nor not now of off often on once only
or other our out over own per same she should so some such than that the their them then there
these they this those through thus to too under until up upon very was we were what when where
which while who whom why will with within without would you your
""".split())


def normalize(text: str) -> str:
    """lower case, accents removed (Epicéa -> epicea), the hybrid sign as x"""
    text = unicodedata.normalize("NFKD", (text or "").replace("×", " x "))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def stem(token: str) -> str:
    """Light English stemmer: plurals only (aphids -> aphid, berries -> berry,
    branches -> branch). Latin names ending in -us / -is stay as they are."""
    if len(token) <= 3 or token.isdigit():
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("sses"):
        return token[:-2]
    if token.endswith(("ches", "shes", "xes", "zes")):
        return token[:-2]
    if token.endswith(("us", "ss", "is", "os", "as")):
        return token
    if token.endswith("s"):
        return token[:-1]
    return token


# words written both together and apart: "rain forest" and "rainforest" must
# give the same term, so that habitat:rainforest finds both
COMPOUND_RE = re.compile(r"\b(rain|cloud)[ -](forests?)\b")


def tokenize(text: str) -> list[str]:
    text = COMPOUND_RE.sub(r"\1\2", normalize(text))
    return [stem(t) for t in TOKEN_RE.findall(text) if t not in STOPWORDS and len(t) > 1]


# ---------------------------------------------------------------------------
# Document -> fields
# ---------------------------------------------------------------------------
def _flatten(part):
    """Strings inside nested lists and dicts (the evidence dicts, lists of plants)."""
    if not part:
        return
    if isinstance(part, str):
        yield part
    elif isinstance(part, dict):
        for value in part.values():
            yield from _flatten(value)
    elif isinstance(part, (list, tuple)):
        for item in part:
            yield from _flatten(item)
    else:
        yield str(part)


def _join(*parts) -> str:
    """One line per string, each line once: ten cultivars of Abies koreana
    with the same sentence "Watch for aphids and adelgids." must not count ten times."""
    return "\n".join(dict.fromkeys(s.strip() for s in _flatten(parts) if s.strip()))


def doc_fields(doc: dict) -> dict[str, str]:
    """Text of every indexed field of a merged TSO + gardenia document."""
    plants = doc.get("gardenia", [])
    habitat_tags = []
    if doc.get("mountain"):
        habitat_tags.append("mountain")       # also when only the altitude says so
    # the title has its own field: the 80 cultivar names of Picea abies would
    # otherwise make the vector of its name long and its cosine with "picea abies" small
    return {
        "title": doc["title"],
        "name": _join(doc.get("common_names"), [n for p in plants for n in p.get("common_names") or []]),
        "synonyms": _join(all_synonyms(doc)),
        "cultivars": _join([s["name"] for s in doc.get("sections", [])], [p["title"] for p in plants]),
        "taxonomy": _join(doc.get("family"), doc.get("genus"),
                          [p.get("plant_type") and " ".join(p["plant_type"]) for p in plants]),
        "distribution": _join(doc.get("distribution"), [p.get("native_to") for p in plants]),
        # every sentence about where the plant grows, from both sites
        "habitat": _join(doc.get("habitat"), doc.get("habitat_from_text"),
                         [p.get("habitat_sentences") for p in plants], habitat_tags,
                         doc.get("mountain_terms")),
        # every sentence about pests and diseases, from both sites
        "pests": _join(doc.get("all_pests"), doc.get("pest_sentences"),
                       [p.get("pest_sentences") for p in plants]),
        "morphology": _join(doc.get("description"), doc.get("life_form"), doc.get("leaf_habit")),
        "garden": _join(*[_join(p.get("exposure"), p.get("soil_type"), p.get("soil_ph"),
                                p.get("soil_drainage"), p.get("characteristics"), p.get("tolerances"),
                                p.get("attracts"), p.get("garden_uses"), p.get("garden_styles"),
                                p.get("maintenance"), p.get("water_needs"), p.get("description"))
                          for p in plants], [f"toxic to {who}" for who in toxic_to(plants)]),
        "text": _join(doc.get("main_text"), [s["text"] for s in doc.get("sections", [])]),
    }


def all_synonyms(doc: dict) -> list[str]:
    """Other scientific names of a document: the TSO synonym list, the other
    names of its cultivars and the synonyms gardenia gives for its plants."""
    names = list(doc.get("synonym_names", []))
    names += [n for s in doc.get("sections", []) for n in s.get("synonyms", [])]
    names += [n for p in doc.get("gardenia", []) for n in p.get("scientific_synonyms") or []]
    # gardenia sells Dasiphora fruticosa as Potentilla fruticosa and gives
    # "Dasiphora fruticosa" as its synonym: that is the TSO name itself
    title = normalize(doc["title"])
    return [n for n in dict.fromkeys(names) if normalize(n) != title]


TOXIC_FIELDS = {"humans": "toxic_humans", "cats": "toxic_cats", "dogs": "toxic_dogs", "horses": "toxic_horses"}


def toxic_to(plants: list[dict]) -> list[str]:
    """Who a gardenia plant is poisonous for: "Toxic" (animals) or
    "Low / Medium / High severity" (humans); "No known toxicity" and "Not toxic" are not."""
    found = set()
    for plant in plants:
        for who, key in TOXIC_FIELDS.items():
            value = (plant.get(key) or "").lower()
            if value == "toxic" or value.endswith("severity"):
                found.add(who)
    return sorted(found)


def doc_info(doc_id: int, doc: dict) -> dict:
    """Short data of a document kept in the index for result lists and filters."""
    plants = doc.get("gardenia", [])
    return {
        "id": doc_id,
        "title": doc["title"],
        "url": doc["url"],
        "kind": doc["kind"],
        "family": doc.get("family"),
        "common": (doc.get("common_names") or [n for p in plants for n in (p.get("common_names") or [])])[:3],
        "zones": doc.get("zones"),
        "usda_tso": (doc.get("usda") or {}).get("raw"),
        "usda_gardenia": sorted({p["hardiness"] for p in plants if p.get("hardiness")}),
        "conservation": doc.get("conservation"),
        "height_m": (doc.get("height") or {}).get("max_m"),
        "mountain": doc.get("mountain", False),
        "pests": doc.get("all_pests", []),
        "synonyms": all_synonyms(doc),
        "toxic_to": toxic_to(plants),
        "gardenia": len(plants),
    }


# ---------------------------------------------------------------------------
# idf and scoring
# ---------------------------------------------------------------------------
def idf_value(method: str, n_docs: int, df: int) -> float:
    if df <= 0:
        return 0.0
    if method == "classic":
        return math.log10(n_docs / df)
    if method == "smooth":
        return math.log10(1 + n_docs / df)
    if method == "probabilistic":
        return max(0.0, math.log10((n_docs - df + 0.5) / (df + 0.5)))
    raise ValueError(f"unknown idf method: {method}")


def tf_weight(tf: int) -> float:
    return 1.0 + math.log10(tf) if tf > 0 else 0.0


class Index:
    def __init__(self, data: dict):
        self.docs = data["docs"]
        self.n_docs = len(self.docs)
        self.fields = data["fields"]
        self.meta = data.get("meta", {})

    @classmethod
    def load(cls, path: Path = INDEX_PATH) -> "Index":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return cls(json.load(f))

    def df(self, field: str, term: str) -> int:
        return len(self.fields[field]["postings"].get(term, ()))

    def idf(self, field: str, term: str, method: str) -> float:
        return idf_value(method, self.n_docs, self.df(field, term))

    def docs_with(self, field: str, term: str) -> set[int]:
        return {d for d, _ in self.fields[field]["postings"].get(term, ())}

    def score_field(self, field: str, terms: list[str], idf_method: str, model: str) -> dict[int, float]:
        """Score of every document that has at least one of the terms in the field."""
        index = self.fields[field]
        postings = index["postings"]
        scores = defaultdict(float)
        query_tf = Counter(terms)

        if model == "tfidf":
            query_weights = {t: tf_weight(n) * self.idf(field, t, idf_method) for t, n in query_tf.items()}
            query_norm = math.sqrt(sum(w * w for w in query_weights.values()))
            if query_norm == 0:
                return {}
            norms = index["norms"][idf_method]
            for term, q_weight in query_weights.items():
                if q_weight == 0:
                    continue
                idf = self.idf(field, term, idf_method)
                for doc_id, tf in postings.get(term, ()):
                    scores[doc_id] += q_weight * tf_weight(tf) * idf
            return {d: s / (query_norm * norms[d]) for d, s in scores.items() if norms[d] > 0}

        if model == "bm25":
            lengths = index["lengths"]
            avg_len = index["avg_length"] or 1.0
            for term in query_tf:
                idf = self.idf(field, term, idf_method)
                if idf == 0:
                    continue
                for doc_id, tf in postings.get(term, ()):
                    norm = BM25_K1 * (1 - BM25_B + BM25_B * lengths[doc_id] / avg_len)
                    scores[doc_id] += idf * tf * (BM25_K1 + 1) / (tf + norm)
            return dict(scores)

        raise ValueError(f"unknown model: {model}")

    def score(self, terms_by_field: dict[str, list[str]], idf_method: str = "classic",
              model: str = "tfidf") -> dict[int, float]:
        """Weighted sum of the field scores."""
        total = defaultdict(float)
        for field, terms in terms_by_field.items():
            if not terms:
                continue
            weight = FIELD_WEIGHTS[field]
            for doc_id, s in self.score_field(field, terms, idf_method, model).items():
                total[doc_id] += weight * s
        return dict(total)


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------
def build(trees_path: Path = TREES_PATH, out_path: Path = INDEX_PATH) -> dict:
    started = time.time()
    docs = []
    postings = {f: defaultdict(list) for f in FIELD_WEIGHTS}
    lengths = {f: [] for f in FIELD_WEIGHTS}
    n_tokens = 0

    with trees_path.open(encoding="utf-8") as f:
        for doc_id, line in enumerate(f):
            doc = json.loads(line)
            docs.append(doc_info(doc_id, doc))
            for field, text in doc_fields(doc).items():
                tokens = tokenize(text)
                n_tokens += len(tokens)
                lengths[field].append(len(tokens))
                for term, tf in Counter(tokens).items():
                    postings[field][term].append([doc_id, tf])

    n_docs = len(docs)
    fields = {}
    for field in FIELD_WEIGHTS:
        field_postings = dict(sorted(postings[field].items()))
        norms = {}
        for method in IDF_METHODS:
            squares = [0.0] * n_docs
            for plist in field_postings.values():
                idf = idf_value(method, n_docs, len(plist))
                for doc_id, tf in plist:
                    squares[doc_id] += (tf_weight(tf) * idf) ** 2
            norms[method] = [round(math.sqrt(s), 6) for s in squares]
        fields[field] = {
            "postings": field_postings,
            "lengths": lengths[field],
            "avg_length": sum(lengths[field]) / max(1, n_docs),
            "norms": norms,
        }

    data = {
        "meta": {
            "documents": n_docs,
            "tokens": n_tokens,
            "built": time.strftime("%Y-%m-%d %H:%M:%S"),
            "field_weights": FIELD_WEIGHTS,
            "vocabulary": {f: len(fields[f]["postings"]) for f in fields},
            "postings": {f: sum(len(p) for p in fields[f]["postings"].values()) for f in fields},
        },
        "docs": docs,
        "fields": fields,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_path, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    meta = data["meta"]
    print("--- index ---")
    print(f"  documents   : {n_docs}")
    print(f"  tokens      : {n_tokens}")
    for field in FIELD_WEIGHTS:
        print(f"  {field:<12}: {meta['vocabulary'][field]:>7} terms, {meta['postings'][field]:>8} postings")
    print(f"  -> {out_path} ({out_path.stat().st_size / 1e6:.1f} MB, {time.time() - started:.0f} s)")
    return meta


if __name__ == "__main__":
    build()
