"""
Tests of the indexer on three small trees: postings, df, both idf methods,
the norms of the documents, and writing and loading the TSV files.

  python -m unittest tests.test_indexer
"""

import math
import tempfile
import unittest
from pathlib import Path

from extractor.tree import Tree
from indexing.indexer import IDF_METHODS, build_index, idf, load_index, tf_weight, write_index


def small_index():
    trees = [
        Tree(key="fagus sylvatica", name="Fagus sylvatica", family="Fagaceae",
             common_names=["European Beech", "Beech"], gardenia_hardiness="hardiness:4-5",
             gardenia_origin="Native to Europe"),
        Tree(key="fagus orientalis", name="Fagus orientalis", family="Fagaceae",
             common_names=["Oriental Beech"]),
        Tree(key="quercus robur", name="Quercus robur", family="Fagaceae",
             common_names=["English Oak"], tso_hardiness="hardiness:5"),
    ]
    return build_index(trees)


class BuildIndex(unittest.TestCase):
    def setUp(self):
        self.docs, self.terms = small_index()

    def test_postings_and_lengths(self):
        self.assertEqual(self.terms["beech"].postings, [(0, 2), (1, 1)])
        self.assertEqual(self.terms["hardiness:5"].postings, [(0, 1), (2, 1)])
        self.assertEqual(self.terms["hardiness:4"].postings, [(0, 1)])
        self.assertEqual([doc.length for doc in self.docs], [8, 5, 6])
        self.assertEqual(self.docs[2].name, "Quercus robur")

    def test_gardenia_origin_is_not_indexed(self):
        self.assertNotIn("nativ", self.terms)
        self.assertNotIn("europ", self.terms)

    def test_idf(self):
        self.assertEqual(idf("classic", 10, 1), 1.0)
        self.assertEqual(self.terms["fagu"].df, 2)
        self.assertAlmostEqual(self.terms["fagu"].idf["classic"], math.log10(3 / 2))
        self.assertEqual(self.terms["fagu"].idf["probabilistic"], 0.0)      # df >= N/2
        self.assertAlmostEqual(self.terms["robur"].idf["probabilistic"], math.log10(2.5 / 1.5))
        self.assertEqual(self.terms["fagacea"].idf, {"classic": 0.0, "probabilistic": 0.0})

    def test_norm(self):
        # Fagus sylvatica: sylvatica, european, hardiness:4 in one document,
        # fagu, hardiness:5 and beech (tf 2) in two, fagacea in all three
        l1, l2 = math.log10(3), math.log10(3 / 2)
        expected = math.sqrt(3 * l1 ** 2 + 2 * l2 ** 2 + (tf_weight(2) * l2) ** 2)
        self.assertAlmostEqual(self.docs[0].norms["classic"], expected)


class WriteAndLoad(unittest.TestCase):
    def test_round_trip(self):
        docs, terms = small_index()
        with tempfile.TemporaryDirectory() as directory:
            write_index(docs, terms, Path(directory))
            loaded_docs, loaded_terms = load_index(Path(directory))

        self.assertEqual([(d.doc_id, d.key, d.name, d.length) for d in loaded_docs],
                         [(d.doc_id, d.key, d.name, d.length) for d in docs])
        self.assertEqual(sorted(loaded_terms), sorted(terms))
        for term, entry in terms.items():
            self.assertEqual(loaded_terms[term].df, entry.df)
            self.assertEqual(loaded_terms[term].postings, entry.postings)
            for method in IDF_METHODS:
                self.assertAlmostEqual(loaded_terms[term].idf[method], entry.idf[method], places=6)
        for loaded, doc in zip(loaded_docs, docs):
            for method in IDF_METHODS:
                self.assertAlmostEqual(loaded.norms[method], doc.norms[method], places=6)


if __name__ == "__main__":
    unittest.main()
