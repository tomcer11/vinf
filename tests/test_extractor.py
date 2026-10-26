"""
Tests of the extractor: text helpers on small snippets, both parsers on real
saved pages (skipped when the page is not on disk).

  python -m unittest tests.test_extractor
"""

import unittest
from pathlib import Path

from extractor.extract_gardenia import is_tree_or_shrub, parse_gardenia_plant
from extractor.extract_tso import paragraphs, parse_tso_genus, parse_tso_species, split_blocks
from extractor.extractor import species_name
from extractor.tree import Tree, clean_html, latin_part, name_key, short_value, short_values, species_key

ROOT = Path(__file__).resolve().parent.parent


def page(relative: str) -> str:
    path = ROOT / relative
    if not path.exists():
        raise unittest.SkipTest(f"{relative} is not on disk")
    return path.read_text(encoding="utf-8")


class TextHelpers(unittest.TestCase):
    def test_clean_html_inline_tags_do_not_split_words(self):
        html = "(<a href=/ref/x/>Tutin <i>et al</i>. 1993</a>)&ensp;<b>Habitat&thinsp;</b>"
        self.assertEqual(clean_html(html), "(Tutin et al. 1993) Habitat")

    def test_clean_html_block_tags_separate_words(self):
        self.assertEqual(clean_html("<p>Leaves ovate<p>Flowers white<br>pink"), "Leaves ovate Flowers white pink")

    def test_clean_html_bean_fractions(self):
        html = "2<span class=fnum>1</span>⁄<span class=fden>2</span> in. long"
        self.assertEqual(clean_html(html), "2 1/2 in. long")

    def test_short_value(self):
        self.assertEqual(short_value("hardiness", "4 - 7"), "hardiness:4-7")
        self.assertEqual(short_value("hardiness", "8–9"), "hardiness:8-9")
        self.assertEqual(short_value("exposure", "Full Sun"), "exposure:full_sun")
        self.assertEqual(short_value("height", "10.7m - 15.2m"), "height:10.7m-15.2m")
        self.assertEqual(short_value("rhs", ""), "")

    def test_short_values(self):
        self.assertEqual(short_values("plant_type", "Cactus & Succulents, Shrubs"),
                         ["plant_type:cactus_and_succulents", "plant_type:shrubs"])

    def test_species_key(self):
        self.assertEqual(species_key("Fagus sylvatica"), ("fagus sylvatica", ""))
        self.assertEqual(species_key("Fagus sylvatica ‘Pendula’"), ("fagus sylvatica", "Pendula"))
        self.assertEqual(species_key("Caryopteris x clandonensis ‘Kew Blue’"),
                         ("caryopteris × clandonensis", "Kew Blue"))
        self.assertEqual(species_key("Pinus mugo var. pumilio"), ("pinus mugo var. pumilio", ""))
        self.assertEqual(species_key("Hydrangea paniculata Quick Fire Fab®"),
                         ("hydrangea paniculata", "Quick Fire Fab"))
        self.assertEqual(species_key("Arctostaphylos uva-ursi"), ("arctostaphylos uva-ursi", ""))

    def test_species_key_without_epithet_uses_whole_name(self):
        self.assertEqual(species_key("Abelia ‘Edward Goucher’"), ("abelia 'edward goucher'", ""))
        self.assertEqual(species_key("Abies in Mexico and Mesoamerica"),
                         ("abies in mexico and mesoamerica", ""))
        self.assertEqual(species_key("Acer platanoides × amplum"), ("acer platanoides × amplum", ""))

    def test_name_key_matches_both_spellings(self):
        self.assertEqual(name_key("Abelia 'Maurice Foster'"), name_key("Abelia ‘Maurice Foster’"))
        self.assertEqual(name_key("Abelia x grandiflora"), "abelia × grandiflora")

    def test_species_name_keeps_original_spelling(self):
        self.assertEqual(species_name("Fagus sylvatica ‘Pendula’", "fagus sylvatica"), "Fagus sylvatica")

    def test_latin_part_drops_authors(self):
        self.assertEqual(latin_part("Linnaea chinensis (R. Br.) A. Braun & Vatke"), "Linnaea chinensis")
        self.assertEqual(latin_part("Fagus sylvatica var. heterophylla Loudon"),
                         "Fagus sylvatica var. heterophylla")

    def test_tree_round_trip(self):
        tree = Tree(key="fagus sylvatica", name="Fagus sylvatica", gardenia_hardiness="hardiness:4-7")
        tree.add_unique("common_names", ["Beech", "beech", "European Beech"])
        self.assertEqual(tree.common_names, ["Beech", "European Beech"])
        self.assertEqual(Tree.from_dict(tree.to_dict()), tree)


class TsoBlocks(unittest.TestCase):
    def test_inline_labels(self):
        block = ("<p>Shrub or tree 5–10 m. Xu 2008. <b>Distribution</b> CHINA: Anhui. "
                 "<b>Habitat</b> Forests. <b>USDA Hardiness Zone</b> 5. <b>Illustration</b> NT71.")
        before, blocks = split_blocks(block)
        self.assertEqual(clean_html(before), "Shrub or tree 5–10 m. Xu 2008.")
        self.assertEqual(clean_html(blocks["distribution"]), "CHINA: Anhui.")
        self.assertEqual(clean_html(blocks["usda"]), "5.")
        self.assertNotIn(None, blocks)


class TsoPages(unittest.TestCase):
    def test_new_format_species(self):
        data = parse_tso_species(page("crawled_pages/tso/pages/articles_fagus_fagus-sylvatica.html"))
        self.assertEqual(data["name"], "Fagus sylvatica")
        self.assertEqual(data["tso_authors"], "L.")
        self.assertEqual(data["family"], "Fagaceae")
        self.assertEqual(data["genus"], "Fagus")
        self.assertIn("European Beech", data["common_names"])
        self.assertIn("Pendula", data["cultivars"])
        self.assertTrue(data["tso_description"].startswith("Tree to 50 m"))
        self.assertIn("Leaves oval-elliptic", data["tso_description"])
        self.assertTrue(data["tso_habitat"].startswith("Native in woods"))
        self.assertIn("Slovakia", data["tso_distribution"])
        self.assertEqual(data["tso_hardiness"], "hardiness:4")
        self.assertEqual(data["tso_rhs"], "rhs:h7")
        self.assertEqual(data["tso_conservation"], "conservation:ne")

    def test_old_format_species(self):
        data = parse_tso_species(page("crawled_pages/tso/pages/articles_quercus_quercus-robur.html"))
        self.assertEqual(data["name"], "Quercus robur")
        self.assertTrue(data["tso_description"].startswith("A deciduous tree"))
        self.assertIn("Leaves stalkless", data["tso_description"])
        self.assertEqual(data["tso_hardiness"], "")
        self.assertIn("Quercus pedunculata", data["synonyms"])

    def test_editorial_note_is_not_the_description(self):
        data = parse_tso_species(page("crawled_pages/tso/pages/articles_brachyglottis_brachyglottis-huntii.html"))
        self.assertTrue(data["tso_description"].startswith("An evergreen shrub or small tree"))

    def test_editorial_note_does_not_cut_the_block(self):
        html = ("<div class=uk-text-small><div uk-alert><h3>Editorial Note</h3><p>Bean treated it as X.</div>"
                "<p>Tree to 20 m.<p><b>Habitat&ensp;</b>Forests.</div><div class=tso-main-text><p>History.")
        data = parse_tso_species(html)
        self.assertEqual(data["tso_description"], "Tree to 20 m.")
        self.assertEqual(data["tso_habitat"], "Forests.")

    def test_genus(self):
        text = parse_tso_genus(page("crawled_pages/tso/pages/articles_fagus.html"))
        self.assertIn("The Beeches are deciduous trees with smooth bark", text)

    def test_old_format_genus(self):
        text = parse_tso_genus(page("crawled_pages/tso/pages/articles_amelanchier.html"))
        self.assertTrue(text.startswith("A genus of shrubs and small trees"))

    def test_gallery_captions_are_not_paragraphs(self):
        html = ('<div class=tso-main-text><a class="uk-inline" href="/x.jpg" '
                'data-caption="<p>Leaves in May. Image J. Smith.</p>" data-alt="Acer" hidden></a>'
                '<p>A genus of trees.')
        self.assertEqual(paragraphs(html), ["A genus of trees."])


class GardeniaPages(unittest.TestCase):
    def test_cultivar_page(self):
        data = parse_gardenia_plant(page("crawled_pages/gardenia/pages/plant_fagus-sylvatica-pendula.html"))
        self.assertEqual(species_key(data["name"]), ("fagus sylvatica", "Pendula"))
        self.assertIn("Weeping Beech", data["title_common_names"])
        self.assertEqual(data["common_names"], ["Beech", "European Beech"])
        self.assertEqual(data["family"], "Fagaceae")
        self.assertIn("lustrous, dark green leaves", data["gardenia_description"])
        self.assertEqual(data["gardenia_origin"], "Native to Central and Southern Europe")
        self.assertEqual(data["gardenia_plant_type"], ["plant_type:trees"])
        self.assertTrue(is_tree_or_shrub(data["gardenia_plant_type"]))
        self.assertEqual(data["gardenia_hardiness"], "hardiness:4-7")
        self.assertEqual(data["gardenia_heat_zones"], "heat_zone:4-9")
        self.assertEqual(data["gardenia_exposure"], ["exposure:full_sun", "exposure:partial_sun"])
        self.assertEqual(data["gardenia_season"],
                         ["season:spring", "season:summer", "season:fall", "season:winter"])
        self.assertEqual(data["gardenia_height"], "height:10.7m-15.2m")
        self.assertEqual(data["gardenia_soil"], ["soil:chalk", "soil:clay", "soil:loam", "soil:sand"])
        self.assertEqual(data["gardenia_drainage"], ["drainage:moist_but_well-drained", "drainage:well-drained"])

    def test_article_page_has_description(self):
        data = parse_gardenia_plant(page("crawled_pages/gardenia/pages/plant_anacardium-occidentale-cashew.html"))
        self.assertTrue(data["gardenia_description"])

    def test_not_a_tree(self):
        self.assertFalse(is_tree_or_shrub(["plant_type:perennials", "plant_type:bulbs"]))
        self.assertTrue(is_tree_or_shrub(["plant_type:conifers", "plant_type:shrubs"]))


if __name__ == "__main__":
    unittest.main()
