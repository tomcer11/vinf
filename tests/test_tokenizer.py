"""
Tests of the tokenizer: Porter's stemmer on the examples of his paper
(M. F. Porter, An algorithm for suffix stripping, 1980), the text pipeline,
the short values and the fields of a Tree.

  python -m unittest tests.test_tokenizer
"""

import unittest
from dataclasses import fields

from extractor.tree import Tree
from indexing import porter
from indexing.tokenizer import (NOT_TOKENIZED, TEXT_FIELDS, VALUE_FIELDS, normalize, tokenize,
                                tree_tokens, value_tokens, words)


class PorterSteps(unittest.TestCase):
    def check(self, step, examples: str):
        for example in examples.split():
            word, expected = example.split("->")
            with self.subTest(word=word):
                self.assertEqual(step(word), expected)

    def test_step1a(self):
        self.check(porter.step1a, "caresses->caress ponies->poni ties->ti caress->caress cats->cat")

    def test_step1b(self):
        self.check(porter.step1b, """
            feed->feed agreed->agree plastered->plaster bled->bled motoring->motor sing->sing
            conflated->conflate troubled->trouble sized->size hopping->hop tanned->tan
            falling->fall hissing->hiss fizzed->fizz failing->fail filing->file""")

    def test_step1c(self):
        self.check(porter.step1c, "happy->happi sky->sky")

    def test_step2(self):
        self.check(porter.step2, """
            relational->relate conditional->condition rational->rational valenci->valence
            hesitanci->hesitance digitizer->digitize conformabli->conformable radicalli->radical
            differentli->different vileli->vile analogousli->analogous vietnamization->vietnamize
            predication->predicate operator->operate feudalism->feudal decisiveness->decisive
            hopefulness->hopeful callousness->callous formaliti->formal sensitiviti->sensitive
            sensibiliti->sensible""")

    def test_step3(self):
        self.check(porter.step3, """
            triplicate->triplic formative->form formalize->formal electriciti->electric
            electrical->electric hopeful->hope goodness->good""")

    def test_step4(self):
        self.check(porter.step4, """
            revival->reviv allowance->allow inference->infer airliner->airlin
            gyroscopic->gyroscop adjustable->adjust defensible->defens irritant->irrit
            replacement->replac adjustment->adjust dependent->depend adoption->adopt
            homologou->homolog communism->commun activate->activ angulariti->angular
            homologous->homolog effective->effect bowdlerize->bowdler""")

    def test_step4_tries_only_the_longest_suffix(self):
        self.check(porter.step4, "agreement->agreement")

    def test_step5(self):
        self.check(porter.step5a, "probate->probat rate->rate cease->ceas")
        self.check(porter.step5b, "controll->control roll->roll")


class PorterWords(unittest.TestCase):
    def test_whole_words(self):
        for word, expected in [("generalizations", "gener"), ("oscillators", "oscil"),
                               ("leaves", "leav"), ("flowers", "flower"), ("flowering", "flower"),
                               ("deciduous", "decidu"), ("fagus", "fagu"), ("cement", "cement"),
                               ("is", "is")]:
            with self.subTest(word=word):
                self.assertEqual(porter.stem(word), expected)


class Tokenize(unittest.TestCase):
    def test_example(self):
        self.assertEqual(tokenize("Deciduous trees for well-drained soils (Bean 1981), to 50 m"),
                         ["decidu", "tree", "well", "drain", "soil"])

    def test_normalize(self):
        self.assertEqual(normalize("Épicéa – Krüssmann"), "epicea - krussmann")

    def test_whole_words_split_on_hyphens_apostrophes_and_hybrid_signs(self):
        self.assertEqual(tokenize("uva-ursi"), ["uva", "ursi"])
        self.assertEqual(tokenize("Bean's and Bean’s"), ["bean", "bean"])
        self.assertEqual(tokenize("Abelia × grandiflora"), ["abelia", "grandiflora"])

    def test_citations_are_dropped_other_parentheses_kept(self):
        self.assertEqual(tokenize("Leaves (ovate) (Hardin 1957a, 1957c) (Landrein et al. 2017; Dirr 2009)"),
                         ["leav", "ovat"])
        self.assertEqual(tokenize("Tutin et al."), ["tutin"])

    def test_urls_are_dropped(self):
        self.assertEqual(tokenize("Crape Myrtles: https://www.lsuagcenter.com/~/media/0136292f/pub1466.pdf "
                                  "(Flora 2005; www.ipni.org) see http://floranorthamerica.org/Cephalanthus"),
                         ["crape", "myrtl", "see"])

    def test_numbers_single_letters_and_stop_words_are_dropped(self):
        self.assertEqual(tokenize("The tree to 50 m, 2.5 cm"), ["tree"])
        self.assertEqual(tokenize("Leaves 4–10 cm, petiole 3 mm, to 30 ft, 2 km"), ["leav", "petiol"])
        self.assertEqual(tokenize("H7 2n 24"), ["h7", "2n"])

    def test_words_are_not_stemmed(self):
        self.assertEqual(words("Deciduous trees (Bean 1981), hardiness:5"), ["deciduous", "trees"])


class ShortValues(unittest.TestCase):
    def test_zone_ranges_are_written_out(self):
        self.assertEqual(value_tokens("hardiness:4-7"),
                         ["hardiness:4", "hardiness:5", "hardiness:6", "hardiness:7"])
        self.assertEqual(value_tokens("heat_zone:1-3"), ["heat_zone:1", "heat_zone:2", "heat_zone:3"])

    def test_odd_tso_zones(self):
        for value, zones in [("hardiness:8b-9a", [8, 9]), ("hardiness:9-_10", [9, 10]),
                             ("hardiness:7a_8b", [7, 8]), ("hardiness:5_-4", [4, 5]),
                             ("hardiness:7b", [7])]:
            with self.subTest(value=value):
                self.assertEqual(value_tokens(value), [f"hardiness:{zone}" for zone in zones])

    def test_other_values_stay_one_token(self):
        for value in ("exposure:full_sun", "rhs:h7", "height:10.7m-15.2m", "conservation:lc"):
            with self.subTest(value=value):
                self.assertEqual(value_tokens(value), [value])
        self.assertEqual(value_tokens(""), [])

    def test_short_values_in_a_query(self):
        self.assertEqual(tokenize("Deciduous shrubs Hardiness:5-6 exposure:full_sun"),
                         ["decidu", "shrub", "hardiness:5", "hardiness:6", "exposure:full_sun"])


class TreeTokens(unittest.TestCase):
    def test_every_field_is_classified(self):
        classified = TEXT_FIELDS + VALUE_FIELDS + NOT_TOKENIZED
        self.assertEqual(len(classified), len(set(classified)))
        self.assertEqual(set(classified), {f.name for f in fields(Tree)})

    def test_tree_tokens(self):
        tree = Tree(key="fagus sylvatica", name="Fagus sylvatica", urls=["https://example.org/x"],
                    common_names=["European Beech"],
                    tso_habitat="Native in woods on well drained soils.",
                    gardenia_hardiness="hardiness:4-5",
                    gardenia_exposure=["exposure:full_sun", "exposure:partial_sun"])
        tokens = tree_tokens(tree)
        self.assertEqual(set(tokens), set(TEXT_FIELDS + VALUE_FIELDS))
        self.assertEqual(tokens["name"], ["fagu", "sylvatica"])
        self.assertEqual(tokens["common_names"], ["european", "beech"])
        self.assertEqual(tokens["tso_habitat"], ["nativ", "wood", "well", "drain", "soil"])
        self.assertEqual(tokens["gardenia_hardiness"], ["hardiness:4", "hardiness:5"])
        self.assertEqual(tokens["gardenia_exposure"], ["exposure:full_sun", "exposure:partial_sun"])
        self.assertEqual(tokens["tso_description"], [])


if __name__ == "__main__":
    unittest.main()
