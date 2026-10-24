"""
Unit tests of the REGEX extractors (extractor.py) and of the gardenia -> TSO mapping

- text extractors on short strings: zones, height, altitude, names, pests,
  habitat sentences, synonyms
- page extractors on 29 downloaded pages: 17 Trees and Shrubs Online pages
  (15 species, 2 genera) and 12 gardenia.net plant pages. The expected values
  were checked by hand in the HTML of each page.

The page tests need the downloaded pages in pages/ and gardenia/pages/;
without them they are skipped.

Usage (from the project directory):
  python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extractor import (NATIVE_RE, clean_sci_name, extract_gardenia, extract_tso,  # noqa: E402
                       find_terms, habitat_sentences, parse_altitude, parse_height, parse_sci_name,
                       parse_zones, pest_sentences, read_page, sentences, split_scientific,
                       synonym_names, PEST_RES)
from indexer import tokenize  # noqa: E402
from mapping import TsoLookup  # noqa: E402

TSO_BASE = "https://www.treesandshrubsonline.org/articles/"
GARDENIA_BASE = "https://www.gardenia.net/plant/"


def tso_page(slug: str) -> dict:
    """slug 'picea/picea-abies' -> record of pages/articles_picea_picea-abies.html"""
    path = ROOT / "pages" / f"articles_{slug.replace('/', '_')}.html"
    if not path.exists():
        raise unittest.SkipTest(f"{path} is not downloaded")
    return extract_tso(read_page(str(path)), f"{TSO_BASE}{slug}/")


def gardenia_page(slug: str) -> dict:
    path = ROOT / "gardenia" / "pages" / f"plant_{slug}.html"
    if not path.exists():
        raise unittest.SkipTest(f"{path} is not downloaded")
    return extract_gardenia(read_page(str(path)), f"{GARDENIA_BASE}{slug}")


# ---------------------------------------------------------------------------
# Text extractors
# ---------------------------------------------------------------------------
class TestTextExtractors(unittest.TestCase):
    def test_zones(self):
        self.assertEqual(parse_zones("4"), {"raw": "4", "min": 4, "max": None})
        self.assertEqual(parse_zones("8b-9a"), {"raw": "8b-9a", "min": 8, "max": 9})
        self.assertEqual(parse_zones("3 - 8"), {"raw": "3 - 8", "min": 3, "max": 8})
        self.assertIsNone(parse_zones(""))
        self.assertIsNone(parse_zones("9-5"))          # range the wrong way round

    def test_height(self):
        self.assertEqual(parse_height("Tree 40–60 m tall, 1–1.5 dbh")["max_m"], 60.0)
        self.assertEqual(parse_height("Tree 30–40(–60) m tall")["max_m"], 60.0)
        self.assertEqual(parse_height("Shrub 30–80 cm high")["max_m"], 0.8)
        self.assertAlmostEqual(parse_height("A tree 60 to over 100 ft high")["max_m"], 30.48)
        self.assertAlmostEqual(parse_height("A deciduous shrub up to 3 or 4 ft high")["min_m"], 0.91)
        self.assertIsNone(parse_height("Leaves 2–3 mm long"))

    def test_altitude(self):
        self.assertEqual(parse_altitude("1,300–2,600 m"), {"min_m": 1300, "max_m": 2600})
        self.assertEqual(parse_altitude("rarely descending below 5,000 ft"), {"min_m": 1524, "max_m": 1524})
        self.assertIsNone(parse_altitude("a tree 100 ft high"))     # a height, not an altitude

    def test_scientific_names(self):
        self.assertEqual(parse_sci_name("Abelia × grandiflora")["hybrid"], True)
        name = parse_sci_name("Picea mariana &#8216;Nana&#8217;")
        self.assertEqual((name["genus"], name["epithet"], name["cultivar"]), ("picea", "mariana", "nana"))
        name = parse_sci_name("Picea pungens var. glauca")
        self.assertEqual((name["rank"], name["infra"]), ("var.", "glauca"))
        self.assertEqual(parse_sci_name("+Laburnocytisus 'Adamii'")["genus"], "laburnocytisus")
        self.assertIsNone(parse_sci_name("Magnolia Cultivars B")["epithet"])

    def test_sentences_keep_abbreviations(self):
        self.assertEqual(sentences("Native of the mountains of S.E. Spain. Hardy."),
                         ["Native of the mountains of S.E. Spain.", "Hardy."])

    def test_pests(self):
        names, evidence = find_terms("Watch for adelgids, aphids and conifer red spider mite.", PEST_RES)
        self.assertEqual(names, ["adelgid", "aphid", "spider mite"])
        names, _ = find_terms("Seed scales 1.5–3 cm, rust-coloured hairs.", PEST_RES)
        self.assertEqual(names, [])                    # cone scales are not scale insects

    def test_any_pest_sentence(self):
        # leafhoppers are not in PEST_PATTERNS, the sentence is kept anyway
        self.assertEqual(pest_sentences("Watch for leafhoppers. Leaves glossy green."),
                         ["Watch for leafhoppers."])
        self.assertEqual(pest_sentences("Top dress annually in autumn with leaf mold."), [])

    def test_habitat_sentences(self):
        text = ("Native of Queensland. It grows in montane rainforest. "
                "It was planted in the woodland garden at Wakehurst.")
        self.assertEqual(habitat_sentences(text, 8),
                         ["Native of Queensland.", "It grows in montane rainforest."])
        self.assertEqual(tokenize("Rain forest"), ["rainforest"])      # = "rainforest"

    def test_synonym_names(self):
        self.assertEqual(clean_sci_name("Picea excelsa (Lam.) Peterm."), "Picea excelsa")
        self.assertEqual(clean_sci_name("Picea abies var. alpestris (Brügger) P.A.Schmidt"),
                         "Picea abies var. alpestris")
        self.assertEqual(clean_sci_name("Picea abies 'Glauca Pendula' hort."), "Picea abies 'Glauca Pendula'")
        # a misapplied name is not a synonym
        self.assertEqual(synonym_names(["Potentilla nepalensis D.Don, not Hook.", "Potentilla rigida Wall."]),
                         ["Potentilla rigida"])

    def test_gardenia_scientific_names(self):
        common, scientific = split_scientific(
            ["Pecan", "Sweet pecan", "Carya pecan", "Juglans illinoensis", "Macadamia nut"], "carya")
        self.assertEqual(scientific, ["Carya pecan", "Juglans illinoensis"])
        self.assertEqual(common, ["Pecan", "Sweet pecan", "Macadamia nut"])

    def test_native(self):
        self.assertEqual(NATIVE_RE.search("Native to Central and Southern Europe, Fagus sylvatica "
                                          "(European Beech) is a tree.").group(1),
                         "Central and Southern Europe")
        self.assertEqual(NATIVE_RE.search("Native to central and northern Europe, Asia and eastern "
                                          "North America").group(1),
                         "central and northern Europe, Asia and eastern North America")


# ---------------------------------------------------------------------------
# Trees and Shrubs Online pages (17)
# ---------------------------------------------------------------------------
class TestTsoPages(unittest.TestCase):
    def test_picea_abies(self):
        r = tso_page("picea/picea-abies")
        self.assertEqual((r["kind"], r["title"], r["family"], r["genus"]),
                         ("species", "Picea abies", "Pinaceae", "Picea"))
        self.assertEqual(r["common_names"][0], "Norway Spruce")
        self.assertEqual(len(r["synonyms"]), 13)
        self.assertIn("Picea excelsa (Lam.) Peterm.", r["synonyms"])
        self.assertIn("Picea excelsa", r["synonym_names"])
        weeping_blue = next(s for s in r["sections"] if s["name"] == "'Weeping Blue'")
        self.assertEqual(weeping_blue["synonyms"], ["Picea abies 'Glauca Pendula'"])
        self.assertEqual(len(r["countries"]), 30)
        self.assertIn("Slovakia", r["countries"])
        self.assertEqual(r["usda"], {"raw": "4", "min": 4, "max": None})
        self.assertEqual((r["rhs"], r["conservation"]), ("H7", "LC"))
        self.assertEqual((r["height"]["min_m"], r["height"]["max_m"]), (40.0, 60.0))
        self.assertEqual(len(r["sections"]), 80)
        self.assertEqual(r["sections"][2]["name"], "'Acrocona'")
        self.assertTrue(r["mountain"])
        self.assertEqual(r["credits"], "Tom Christian (2025)")

    def test_abies_alba(self):
        r = tso_page("abies/abies-alba")
        self.assertEqual(r["usda"], {"raw": "4-7", "min": 4, "max": 7})
        self.assertEqual(r["common_names"][0], "Silver Fir")
        self.assertEqual(r["height"]["max_m"], 60.0)
        self.assertTrue(r["mountain"])
        self.assertIn("aphid", r["pests"])           # "woolly aphid (Adelges nordmanniana)"

    def test_ailanthus_editorial_note(self):
        # the Editorial Note box inside the summary block must not end it
        r = tso_page("ailanthus/ailanthus-altissima")
        self.assertTrue(r["editorial_note"].startswith("The International Dendrology Society"))
        self.assertTrue(r["description"].startswith("A tree to 30 m tall"))
        self.assertEqual(r["countries"][0], "China")
        self.assertTrue(r["habitat"].startswith("Mountain forests and open woodlands"))
        self.assertEqual(r["usda"], {"raw": "5a", "min": 5, "max": None})
        self.assertEqual((r["rhs"], r["conservation"], r["awards"]), ("H6", "NE", "AGM"))

    def test_hymenosporum_rainforest(self):
        r = tso_page("hymenosporum/hymenosporum-flavum")
        self.assertEqual(r["habitat"], "Rain forest and tall, open forest")
        self.assertIn("rainforest", tokenize(r["habitat"]))
        self.assertEqual(r["usda"]["raw"], "9a")

    def test_rhododendron_floribundum(self):
        r = tso_page("rhododendron/rhododendron-floribundum")
        self.assertEqual(r["habitat"], "1,300–2,600 m")
        self.assertEqual(r["altitude"], {"min_m": 1300, "max_m": 2600})
        self.assertTrue(r["mountain"])               # by altitude only
        self.assertEqual(r["countries"], ["China"])
        self.assertEqual(r["rhs"], "H5")
        self.assertEqual(r["life_form"], ["shrub", "tree"])
        self.assertEqual((r["height"]["min_m"], r["height"]["max_m"]), (2.0, 5.0))

    def test_acer_cascade_cultivar_page(self):
        r = tso_page("acer/acer-cascade")
        self.assertEqual(r["title"], "Acer 'Cascade'")
        self.assertEqual(r["name"]["cultivar"], "cascade")
        self.assertIsNone(r["name"]["epithet"])
        self.assertEqual((r["family"], r["rhs"], r["usda"]), ("Sapindaceae", "H5", None))

    def test_magnolia_cultivars_b(self):
        r = tso_page("magnolia/magnolia-cultivars-b")
        names = [s["name"] for s in r["sections"]]
        self.assertIn("'Ballerina'", names)
        self.assertEqual(names[0], "BABY GRAND®")
        self.assertEqual(r["sections"][1]["id"], "19178")

    def test_abelia_hybrid(self):
        r = tso_page("abelia/abelia-x-grandiflora")
        self.assertTrue(r["name"]["hybrid"])
        self.assertEqual(r["usda"], {"raw": "5b", "min": 5, "max": None})
        self.assertEqual((r["rhs"], r["family"]), ("H6", "Caprifoliaceae"))
        self.assertEqual(r["leaf_habit"], ["semi-evergreen"])

    def test_fraxinus_excelsior_old_article(self):
        r = tso_page("fraxinus/fraxinus-excelsior")
        self.assertEqual(r["description"], "")       # Bean's article: no summary block
        self.assertAlmostEqual(r["height"]["max_m"], 42.67)   # "100 to 140 ft"
        self.assertFalse(r["mountain"])

    def test_ulmus_procera(self):
        r = tso_page("ulmus/ulmus-procera")
        self.assertEqual(r["common_names"], ["English Elm"])
        self.assertIn("dutch elm disease", r["pests"])

    def test_pinus_cembra_mountain_from_text(self):
        r = tso_page("pinus/pinus-cembra")
        self.assertTrue(r["habitat_from_text"].startswith("Native of the Alps"))
        self.assertEqual(r["altitude"], {"min_m": 1524, "max_m": 1524})   # 5,000 ft
        self.assertTrue(r["mountain"])
        self.assertIn("tatras", r["mountain_terms"])

    def test_quercus_robur(self):
        r = tso_page("quercus/quercus-robur")
        self.assertIn("Pedunculate Oak", r["common_names"])
        self.assertEqual(r["sections"][0]["name"], "'Atropurpurea'")

    def test_taxus_baccata(self):
        r = tso_page("taxus/taxus-baccata")
        self.assertEqual((r["family"], r["common_names"]), ("Taxaceae", ["Common Yew"]))
        self.assertEqual(len(r["sections"]), 28)

    def test_castanea_dentata(self):
        r = tso_page("castanea/castanea-dentata")
        self.assertIn("blight", r["pests"])          # chestnut blight
        self.assertIn("chestnut blight", r["pest_evidence"]["blight"][0].lower())

    def test_larix_decidua(self):
        r = tso_page("larix/larix-decidua")
        self.assertEqual(r["usda"], {"raw": "3-6", "min": 3, "max": 6})
        self.assertEqual(r["altitude"]["max_m"], 2500)
        self.assertIn("tree line", r["mountain_terms"])
        self.assertEqual(r["leaf_habit"], ["deciduous"])
        self.assertEqual((r["height"]["min_m"], r["height"]["max_m"]), (30.0, 55.0))

    def test_genus_picea(self):
        r = tso_page("picea")
        self.assertEqual((r["kind"], r["title"], r["family"]), ("genus", "Picea", "Pinaceae"))
        self.assertEqual(r["common_names"], ["Spruces"])
        self.assertEqual(len(r["species_in_genus"]), 42)
        self.assertIn("aphid", r["pests"])           # Green Spruce Aphid

    def test_genus_abies(self):
        r = tso_page("abies")
        self.assertEqual(r["kind"], "genus")
        self.assertEqual(r["common_names"][0], "Silver Firs")
        self.assertEqual(len(r["species_in_genus"]), 66)


# ---------------------------------------------------------------------------
# gardenia.net plant pages (12)
# ---------------------------------------------------------------------------
class TestGardeniaPages(unittest.TestCase):
    def test_picea_abies(self):
        r = gardenia_page("picea-abies")
        self.assertEqual((r["title"], r["scientific_name"]), ("Picea abies (Norway Spruce)", "Picea abies"))
        self.assertEqual(r["common_names"][:2], ["Norway Spruce", "European Spruce"])
        self.assertEqual(r["usda"], {"raw": "3 - 8", "min": 3, "max": 8})
        self.assertEqual(r["plant_type"], ["Conifers", "Trees"])
        self.assertEqual((r["family"], r["genus"]), ("Pinaceae", "Picea"))
        self.assertEqual(r["height"], {"min_m": 12.2, "max_m": 18.3})
        self.assertEqual(r["tolerances"], ["Deer", "Clay Soil", "Wind"])
        self.assertEqual(r["pests"], ["adelgid", "aphid", "spider mite"])
        self.assertEqual(r["native_to"], "Europe")
        self.assertEqual(r["toxic_dogs"], "No known toxicity")
        self.assertIn("Watch for adelgids, aphids and conifer red spider mite.", r["pest_sentences"])
        self.assertEqual(r["scientific_synonyms"], [])   # all its other names are common names

    def test_hepatica_perennial(self):
        r = gardenia_page("hepatica-nobilis")
        self.assertEqual(r["plant_type"], ["Perennials"])
        self.assertTrue(r["award_agm"])
        self.assertTrue(r["pest_free"])              # "Generally disease free."
        self.assertEqual(r["pests"], ["slug and snail"])
        self.assertEqual(r["scientific_synonyms"], ["Anemone hepatica", "Hepatica triloba"])
        self.assertNotIn("Anemone hepatica", r["common_names"])
        self.assertEqual(r["native_to"], "central and northern Europe, Asia and eastern North America")
        self.assertEqual(r["height"], {"min_m": 0.08, "max_m": 0.1})

    def test_picea_mariana_cultivar(self):
        r = gardenia_page("picea-mariana-nana")
        self.assertEqual((r["name"]["epithet"], r["name"]["cultivar"]), ("mariana", "nana"))
        self.assertEqual(r["usda"]["raw"], "3 - 7")

    def test_picea_pungens_variety(self):
        r = gardenia_page("picea-pungens-var-glauca")
        self.assertEqual((r["name"]["rank"], r["name"]["infra"]), ("var.", "glauca"))
        self.assertEqual(r["usda"], {"raw": "2 - 8", "min": 2, "max": 8})
        self.assertEqual(r["native_to"], "the central and southern Rocky Mountains")

    def test_abelia_hybrid_cultivar(self):
        r = gardenia_page("abelia-x-grandiflora-little-richard-glossy-abelia")
        self.assertTrue(r["name"]["hybrid"])
        self.assertEqual(r["name"]["cultivar"], "little richard")
        self.assertIn("powdery mildew", r["pests"])
        self.assertEqual(r["plant_type"], ["Shrubs"])

    def test_acer_palmatum_bloodgood(self):
        r = gardenia_page("acer-palmatum-bloodgood-japanese-maple")
        self.assertEqual(r["name"]["cultivar"], "bloodgood")
        self.assertEqual(r["usda"]["raw"], "5 - 8")
        self.assertEqual(r["pests"], ["aphid", "wilt"])
        self.assertTrue(r["award_agm"])

    def test_betula_pendula(self):
        r = gardenia_page("betula-pendula-silver-birch")
        self.assertEqual(r["usda"], {"raw": "2 - 7", "min": 2, "max": 7})
        self.assertIn("sawfly", r["pests"])
        self.assertIn("aphid", r["pests"])

    def test_castanea_dentata(self):
        r = gardenia_page("castanea-dentata-american-chestnut-grow-care-guide")
        self.assertIn("blight", r["pests"])
        self.assertEqual(r["scientific_synonyms"], ["Castanea americana"])
        self.assertEqual(r["toxic_dogs"], "Not toxic")
        self.assertEqual(r["native_to"], "the eastern United States and southeastern Canada")

    def test_fagus_sylvatica(self):
        r = gardenia_page("fagus-sylvatica")
        self.assertEqual(r["usda"]["raw"], "4 - 7")
        self.assertEqual(r["toxic_dogs"], "Toxic")
        self.assertEqual(r["garden_uses"], ["Hedges And Screens"])
        self.assertEqual(r["native_to"], "Central and Southern Europe")
        # Beech scale is not in PEST_PATTERNS, its sentence is kept for pest:<word>
        self.assertTrue(any("Beech scale" in s for s in r["pest_sentences"]))

    def test_hydrangea_limelight(self):
        r = gardenia_page("hydrangea-paniculata-limelight")
        self.assertEqual(r["scientific_name"], "Hydrangea paniculata ‘Limelight’")
        self.assertEqual(r["name"]["cultivar"], "limelight")
        self.assertIn("Salt", r["tolerances"])
        self.assertEqual(r["attracts"], ["Butterflies", "Bees"])

    def test_osmanthus_fragrans(self):
        r = gardenia_page("osmanthus-fragrans")
        self.assertEqual(r["name"]["cultivar"], "conger yellow")
        self.assertEqual(r["usda"], {"raw": "8 - 11", "min": 8, "max": 11})
        self.assertEqual(r["plant_type"], ["Shrubs", "Trees"])

    def test_taxus_baccata_fastigiata(self):
        r = gardenia_page("taxus-baccata-fastigiata")
        self.assertEqual(r["usda"]["raw"], "7 - 8")
        self.assertIn("Full Shade", r["tolerances"])
        self.assertEqual(r["toxic_dogs"], "Toxic")
        self.assertEqual(r["plant_type"], ["Conifers", "Shrubs"])


# ---------------------------------------------------------------------------
# gardenia -> TSO mapping
# ---------------------------------------------------------------------------
def tso_record(title, kind="species", synonyms=(), sections=()):
    """sections: (id, name) or (id, name, [other names of the cultivar])"""
    return {"title": title, "kind": kind, "name": parse_sci_name(title), "synonyms": list(synonyms),
            "sections": [{"id": s[0], "name": s[1], "synonyms": list(s[2]) if len(s) > 2 else []}
                         for s in sections]}


def gardenia_record(title, plant_type=("Trees",), synonyms=()):
    return {"title": title, "name": parse_sci_name(title), "plant_type": list(plant_type),
            "scientific_synonyms": list(synonyms)}


class TestMapping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lookup = TsoLookup([
            tso_record("Picea abies", sections=[("10731", "'Acrocona'"),
                                                ("32754", "'Weeping Blue'", ["Picea abies 'Glauca Pendula'"])]),
            tso_record("Picea likiangensis aggregate"),
            tso_record("Picea likiangensis"),
            tso_record("Dasiphora arbuscula", synonyms=["Potentilla nepalensis D.Don, not Hook."]),
            tso_record("Dasiphora fruticosa", synonyms=["Potentilla fruticosa L."]),
            tso_record("Magnolia Cultivars B", sections=[("19178", "'Ballerina'")]),
            tso_record("Salvia", kind="genus"),
        ])

    def match(self, title, plant_type=("Trees",), synonyms=()):
        level, page, anchor = self.lookup.match(gardenia_record(title, plant_type, synonyms))
        return level, page, anchor

    def test_cultivar_section(self):
        self.assertEqual(self.match("Picea abies ‘Acrocona’"), ("cultivar", 0, "10731"))
        self.assertEqual(self.match("Magnolia ‘Ballerina’"), ("cultivar", 5, "19178"))

    def test_cultivar_by_its_other_name(self):
        # TSO: 'Weeping Blue', alternative name 'Glauca Pendula'
        self.assertEqual(self.match("Picea abies ‘Glauca Pendula’"), ("cultivar", 0, "32754"))

    def test_synonym_given_by_gardenia(self):
        # neither name nor TSO synonym, but gardenia lists "Dasiphora fruticosa"
        self.assertEqual(self.match("Potentilla davurica ‘Abbotswood’", ["Shrubs"], ["Dasiphora fruticosa"]),
                         ("synonym", 4, None))

    def test_species(self):
        self.assertEqual(self.match("Picea abies ‘Little Gem’"), ("species", 0, None))
        self.assertEqual(self.match("Picea likiangensis"), ("species", 2, None))   # not the aggregate

    def test_synonym(self):
        self.assertEqual(self.match("Potentilla fruticosa ‘Abbotswood’", ["Shrubs"]), ("synonym", 4, None))
        # a misapplied name ("not Hook.") must not be used
        self.assertEqual(self.match("Potentilla nepalensis", ["Perennials"])[0], "none")

    def test_genus_only_for_woody_plants(self):
        self.assertEqual(self.match("Salvia ‘Hot Lips’", ["Shrubs"])[0], "genus")
        self.assertEqual(self.match("Salvia nemorosa", ["Perennials"])[0], "none")


if __name__ == "__main__":
    unittest.main()
