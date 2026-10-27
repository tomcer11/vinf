"""
Search: the trees most similar to a text, by the cosine of TF-IDF vectors
over the index of indexer.py.

  1. the query goes through the same tokenize() as the trees
     ("weeping beeches" -> weep beech, "hardiness:5" stays one term)
  2. weights as in the index, with idf classic or smooth:
       w(t, q) = (1 + log10 tf_q) * idf(t)      tf_q = count of the term in the query
       w(t, d) = (1 + log10 tf_d) * idf(t)
     terms that are not in the index or have idf 0 (classic, a term in all
     documents) are left out
  3. cos(q, d) = sum_t w(t, q) * w(t, d) / (|q| * |d|), |d| from output/index/docs.tsv;
     only the postings of the query terms are read, term by term
  4. the trees with the highest cosine, 10 by default

Usage:
  python search.py deciduous tree for clay soil
  python search.py "weeping beech" --top 5
  python search.py "weeping beech" --idf smooth
"""

import argparse
import heapq
import math
from collections import Counter, defaultdict

from indexing.indexer import IDF_METHODS, Doc, Term, load_index, tf_weight
from indexing.tokenizer import tokenize

DEFAULT_TOP = 10


def query_weights(tokens: list[str], terms: dict[str, Term], method: str) -> dict[str, float]:
    """w(t, q) of the query terms that are in the index and have idf > 0."""
    weights = {}
    for term, tf in Counter(tokens).items():
        entry = terms.get(term)
        if entry and entry.idf[method] > 0:
            weights[term] = tf_weight(tf) * entry.idf[method]
    return weights


def search(query: str, docs: list[Doc], terms: dict[str, Term], method: str = "classic",
           top: int = DEFAULT_TOP) -> tuple[list[tuple[float, int]], int]:
    """(the top (cosine, doc_id) pairs, best first; the number of trees with a
    query term). Equal cosines keep the order of the index (by key)."""
    weights = query_weights(tokenize(query), terms, method)
    dot = defaultdict(float)
    for term, w_query in weights.items():
        entry = terms[term]
        for doc_id, tf in entry.postings:
            dot[doc_id] += w_query * tf_weight(tf) * entry.idf[method]

    # a tree with a query term of idf > 0 has |d| > 0
    query_norm = math.sqrt(sum(w * w for w in weights.values()))
    hits = [(score / (query_norm * docs[doc_id].norms[method]), doc_id) for doc_id, score in dot.items()]
    return heapq.nlargest(top, hits, key=lambda hit: (hit[0], -hit[1])), len(dot)


def print_results(query: str, docs: list[Doc], terms: dict[str, Term], method: str, top: int):
    tokens = list(dict.fromkeys(tokenize(query)))
    weights = query_weights(tokens, terms, method)
    used = "  ".join(f"{term} {terms[term].idf[method]:.2f}" for term in weights)
    print(f"Query terms (idf {method}): {used or '-'}")
    missing = [term for term in tokens if term not in terms]
    if missing:
        print("Not in the index: " + " ".join(missing))
    ignored = [term for term in tokens if term in terms and term not in weights]
    if ignored:
        print(f"Ignored, idf {method} is 0: " + " ".join(ignored))

    hits, n_matching = search(query, docs, terms, method, top)
    if not hits:
        print("\nNo tree matches the query")
        return
    print(f"Top {len(hits)} of {n_matching} trees with a query term\n")
    in_docs = {term: {doc_id for doc_id, _ in terms[term].postings} for term in weights}
    for rank, (score, doc_id) in enumerate(hits, 1):
        found = " ".join(term for term in weights if doc_id in in_docs[term])
        print(f"  {rank:3}  {score:.4f}  {docs[doc_id].name:40}  {found}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query", nargs="+", help="the text to search for")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP,
                        help=f"number of trees to show (default {DEFAULT_TOP})")
    parser.add_argument("--idf", choices=IDF_METHODS, default="classic", help="idf method (default classic)")
    args = parser.parse_args()

    query = " ".join(args.query)
    docs, terms = load_index(only=set(tokenize(query)))
    print_results(query, docs, terms, args.idf, args.top)


if __name__ == "__main__":
    main()
