"""
Tests of the search on the three small trees of tests.test_indexer: the
order of the results, the cosine, the limits, queries without usable terms,
and loading only the terms of a query.

  python -m unittest tests.test_search
"""

import math
import tempfile
import unittest
from pathlib import Path

from indexing.indexer import load_index, write_index
from search import query_weights, search
from tests.test_indexer import small_index


class Search(unittest.TestCase):
    def setUp(self):
        # 0 Fagus sylvatica (beech twice), 1 Fagus orientalis, 2 Quercus robur
        self.docs, self.terms = small_index()

    def test_order(self):
        hits, n_matching = search("beech", self.docs, self.terms)
        self.assertEqual([doc_id for _, doc_id in hits], [0, 1])
        self.assertEqual(n_matching, 2)

    def test_cosine(self):
        # Fagus orientalis: fagu and beech in two trees, orientali and orient in one,
        # fagacea in all three (idf 0); the query "beech" has the one term beech
        hits, _ = search("beech", self.docs, self.terms)
        l1, l2 = math.log10(3), math.log10(3 / 2)
        self.assertAlmostEqual(dict((d, s) for s, d in hits)[1], l2 / math.sqrt(2 * l2 ** 2 + 2 * l1 ** 2))

    def test_top_limits_the_results(self):
        hits, n_matching = search("Fagaceae beech hardiness:5", self.docs, self.terms, top=1)
        self.assertEqual(len(hits), 1)
        self.assertEqual(n_matching, 3)

    def test_queries_without_usable_terms(self):
        for query in ("", "the and of", "magnolia", "Fagaceae"):     # fagacea: idf 0
            with self.subTest(query=query):
                self.assertEqual(search(query, self.docs, self.terms), ([], 0))

    def test_zero_probabilistic_idf_is_ignored(self):
        self.assertEqual(set(query_weights(["fagu", "robur"], self.terms, "probabilistic")), {"robur"})
        self.assertEqual(search("Fagus", self.docs, self.terms, method="probabilistic"), ([], 0))
        self.assertEqual(len(search("Fagus", self.docs, self.terms, method="classic")[0]), 2)

    def test_load_only_the_query_terms(self):
        with tempfile.TemporaryDirectory() as directory:
            write_index(self.docs, self.terms, Path(directory))
            docs, terms = load_index(Path(directory), only={"beech", "robur"})
        self.assertEqual(len(docs), 3)
        self.assertEqual(set(terms), {"beech", "robur"})
        self.assertEqual(terms["beech"].postings, self.terms["beech"].postings)


if __name__ == "__main__":
    unittest.main()
