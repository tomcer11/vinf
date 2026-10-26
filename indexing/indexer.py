"""
Own inverted index over the trees of output/data/trees.jsonl.

Document = one Tree (one species). Its terms are the tokens of all its text
and short value fields (tokenizer.tree_tokens) merged into one vector;
gardenia_origin is left out, it is a copy of one of gardenia_highlights.

  term -> [(doc_id, tf), ...]       tf = how many times the term is in the tree

Weights, N = number of documents, df = number of documents with the term:
  tf weight      1 + log10(tf)
  classic        idf = log10(N / df)
  probabilistic  idf = max(0, log10((N - df + 0.5) / (df + 0.5)))
                 (Robertson / Sparck Jones, 0 for a term in half of the documents or more)
  w(t, d) = (1 + log10 tf) * idf(t). The length |d| = sqrt(sum of w(t, d)^2)
  is stored for both idf methods, so that the search can compute the cosine.

Files (tab separated, with a header):
  output/index/docs.tsv    doc_id  key  name  length  norm_classic  norm_probabilistic
  output/index/terms.tsv   term  df  idf_classic  idf_probabilistic  postings
                           terms sorted, postings 'doc_id:tf,doc_id:tf' sorted by doc_id

Usage:
  python -m indexing.indexer                    # build the index from output/data/trees.jsonl
  python -m indexing.indexer --term deciduous   # df, idf and the documents of a term
"""

import argparse
import json
import math
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from extractor.tree import Tree
from indexing.tokenizer import TEXT_FIELDS, VALUE_FIELDS, tokenize, tree_tokens

TREES_PATH = Path("./output/data/trees.jsonl")
INDEX_DIR = Path("./output/index")
DOCS_FILE = "docs.tsv"
TERMS_FILE = "terms.tsv"

IDF_METHODS = ("classic", "probabilistic")
INDEX_FIELDS = [name for name in TEXT_FIELDS + VALUE_FIELDS if name != "gardenia_origin"]


@dataclass
class Doc:
    doc_id: int
    key: str
    name: str
    length: int                     # number of tokens
    norms: dict[str, float]         # |d| for every idf method


@dataclass
class Term:
    df: int
    idf: dict[str, float]
    postings: list[tuple[int, int]]     # (doc_id, tf), sorted by doc_id


def idf(method: str, n_docs: int, df: int) -> float:
    if method == "classic":
        return math.log10(n_docs / df)
    if method == "probabilistic":
        return max(0.0, math.log10((n_docs - df + 0.5) / (df + 0.5)))
    raise ValueError(f"unknown idf method: {method}")


def tf_weight(tf: int) -> float:
    return 1 + math.log10(tf)


def doc_terms(tree: Tree) -> Counter:
    """tf of every term of a tree."""
    tokens = tree_tokens(tree)
    return Counter(token for name in INDEX_FIELDS for token in tokens[name])


def build_index(trees: list[Tree]) -> tuple[list[Doc], dict[str, Term]]:
    docs, postings = [], {}
    for doc_id, tree in enumerate(trees):
        tfs = doc_terms(tree)
        docs.append(Doc(doc_id, tree.key, tree.name, sum(tfs.values()), {}))
        for term, tf in tfs.items():        # documents come in order: postings stay sorted
            postings.setdefault(term, []).append((doc_id, tf))

    n_docs = len(docs)
    terms = {}
    squares = {method: [0.0] * n_docs for method in IDF_METHODS}
    for term in sorted(postings):
        plist = postings[term]
        values = {method: idf(method, n_docs, len(plist)) for method in IDF_METHODS}
        terms[term] = Term(len(plist), values, plist)
        for doc_id, tf in plist:
            for method in IDF_METHODS:
                squares[method][doc_id] += (tf_weight(tf) * values[method]) ** 2
    for doc in docs:
        doc.norms = {method: math.sqrt(squares[method][doc.doc_id]) for method in IDF_METHODS}
    return docs, terms


def write_index(docs: list[Doc], terms: dict[str, Term], directory: Path = INDEX_DIR):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / DOCS_FILE).open("w", encoding="utf-8", newline="\n") as out:
        out.write("\t".join(["doc_id", "key", "name", "length"] + [f"norm_{m}" for m in IDF_METHODS]) + "\n")
        for doc in docs:
            row = [str(doc.doc_id), doc.key, doc.name, str(doc.length)]
            out.write("\t".join(row + [f"{doc.norms[m]:.6f}" for m in IDF_METHODS]) + "\n")
    with (directory / TERMS_FILE).open("w", encoding="utf-8", newline="\n") as out:
        out.write("\t".join(["term", "df"] + [f"idf_{m}" for m in IDF_METHODS] + ["postings"]) + "\n")
        for term in sorted(terms):
            entry = terms[term]
            postings = ",".join(f"{doc_id}:{tf}" for doc_id, tf in entry.postings)
            row = [term, str(entry.df)] + [f"{entry.idf[m]:.6f}" for m in IDF_METHODS]
            out.write("\t".join(row + [postings]) + "\n")


def load_index(directory: Path = INDEX_DIR, only: set[str] | None = None) -> tuple[list[Doc], dict[str, Term]]:
    """All documents, and all terms or only the terms in `only` (the terms of
    a query: the postings of the other lines are not parsed)."""
    docs = []
    with (directory / DOCS_FILE).open(encoding="utf-8") as lines:
        next(lines)                                         # header
        for line in lines:
            doc_id, key, name, length, *norms = line.rstrip("\n").split("\t")
            docs.append(Doc(int(doc_id), key, name, int(length),
                            {m: float(v) for m, v in zip(IDF_METHODS, norms)}))
    terms = {}
    with (directory / TERMS_FILE).open(encoding="utf-8") as lines:
        next(lines)
        for line in lines:
            if only is not None and line.split("\t", 1)[0] not in only:
                continue
            term, df, *idfs, postings = line.rstrip("\n").split("\t")
            terms[term] = Term(int(df), {m: float(v) for m, v in zip(IDF_METHODS, idfs)},
                               [tuple(map(int, p.split(":"))) for p in postings.split(",")])
    return docs, terms


def print_summary(docs: list[Doc], terms: dict[str, Term], seconds: float):
    n_docs = len(docs)
    tokens = sum(doc.length for doc in docs)
    value_terms = sum(1 for term in terms if ":" in term)
    rows = [
        ("documents (trees)", n_docs),
        ("terms", len(terms)),
        ("  text terms", len(terms) - value_terms),
        ("  short value terms", value_terms),
        ("postings (term, document pairs)", sum(entry.df for entry in terms.values())),
        ("tokens", tokens),
        ("average tokens per document", round(tokens / n_docs)),
        ("terms in one document only", sum(1 for entry in terms.values() if entry.df == 1)),
        ("terms with probabilistic idf 0 (df >= N/2)",
         sum(1 for entry in terms.values() if entry.idf["probabilistic"] == 0)),
    ]
    print()
    for label, value in rows:
        print(f"  {label:45} {value:10}")
    for name in (DOCS_FILE, TERMS_FILE):
        size = (INDEX_DIR / name).stat().st_size / 1e6
        print(f"  {'size of ' + str(INDEX_DIR / name):45} {size:7.1f} MB")

    print(f"\n  {'terms with the highest df':25} {'df':>6} {'idf classic':>12} {'probabilistic':>14}")
    for term, entry in sorted(terms.items(), key=lambda item: -item[1].df)[:10]:
        print(f"  {term:25} {entry.df:6} {entry.idf['classic']:12.4f} {entry.idf['probabilistic']:14.4f}")
    print(f"\nDone in {seconds:.0f} s")


def show_term(text: str):
    tokens = tokenize(text)
    docs, terms = load_index(only=set(tokens))
    for term in tokens:
        entry = terms.get(term)
        if not entry:
            print(f"{term}: not in the index")
            continue
        print(f"{term}: df {entry.df}, idf classic {entry.idf['classic']:.4f}, "
              f"probabilistic {entry.idf['probabilistic']:.4f}")
        for doc_id, tf in sorted(entry.postings, key=lambda posting: -posting[1])[:10]:
            weights = "  ".join(f"w_{m} {tf_weight(tf) * entry.idf[m]:.3f}" for m in IDF_METHODS)
            print(f"  tf {tf:3}  {weights}  {docs[doc_id].name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--term", help="print df, idf and the documents of the terms of this text")
    args = parser.parse_args()

    if args.term is not None:
        show_term(args.term)
        return
    start = time.time()
    with TREES_PATH.open(encoding="utf-8") as lines:
        trees = [Tree.from_dict(json.loads(line)) for line in lines]
    print(f"Indexing {len(trees)} trees from {TREES_PATH}", flush=True)
    docs, terms = build_index(trees)
    write_index(docs, terms)
    print(f"Wrote {INDEX_DIR / DOCS_FILE} and {INDEX_DIR / TERMS_FILE}")
    print_summary(docs, terms, time.time() - start)


if __name__ == "__main__":
    main()
