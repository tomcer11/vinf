"""
Tests of the extractor: text helpers on small snippets, both parsers on real
saved pages (skipped when the page is not on disk).

  python -m unittest tests.test_extractor
"""

import unittest
from pathlib import Path

from extractor.extract_gardenia import is_tree_or_shrub, parse_gardenia_plant, plant_type
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

    def test_genus_without_editorial_note(self):
        text = parse_tso_genus(page("crawled_pages/tso/pages/articles_betula.html"))
        self.assertTrue(text.startswith("One hundred and two species of Betula are recognised"))
        self.assertNotIn("Editorial Note", text)

    def test_subspecies(self):
        data = parse_tso_species(page("crawled_pages/tso/pages/articles_betula_betula-utilis-subsp-jacquemontii.html"))
        self.assertEqual(data["name"], "Betula utilis subsp. jacquemontii")
        self.assertEqual(data["tso_authors"], "(Spach) Kitam.")
        self.assertEqual(species_key(data["name"]), ("betula utilis subsp. jacquemontii", ""))
        self.assertEqual(data["synonyms"][:2], ["Betula jacquemontii", "Betula utilis var. jacquemontii"])
        self.assertEqual(data["tso_habitat"], "Forests, stony river beds, screes and rocky places in the mountains.")

    def test_hybrid(self):
        data = parse_tso_species(page("crawled_pages/tso/pages/articles_aesculus_aesculus-x-neglecta.html"))
        self.assertEqual(data["name"], "Aesculus × neglecta")
        self.assertEqual(data["tso_authors"], "Lindl.")
        self.assertEqual(data["family"], "Sapindaceae")
        self.assertEqual(species_key(data["name"]), ("aesculus × neglecta", ""))

    def test_cultivar_without_epithet(self):
        data = parse_tso_species(page("crawled_pages/tso/pages/articles_abelia_abelia-maurice-foster.html"))
        self.assertEqual(data["name"], "Abelia 'Maurice Foster'")
        self.assertEqual(data["tso_authors"], "")
        self.assertEqual(species_key(data["name"]), ("abelia 'maurice foster'", ""))
        self.assertEqual(data["tso_habitat"], "Mountain forests")
        self.assertEqual(data["tso_hardiness"], "hardiness:6b")
        self.assertEqual(data["tso_rhs"], "rhs:h5")
        self.assertEqual(data["tso_conservation"], "")

    def test_zone_range_and_iucn_code(self):
        data = parse_tso_species(page("crawled_pages/tso/pages/articles_abies_abies-alba.html"))
        self.assertTrue(data["tso_description"].startswith("Tree to 60 m tall"))
        self.assertEqual(data["common_names"][:2], ["Silver Fir", "European Silver Fir"])
        self.assertEqual(data["synonyms"], ["Abies alba subsp. apennina", "Abies pectinata"])
        self.assertEqual(data["cultivars"][:3], ["Compacta", "Dwarf Cultivars", "Fastigiata"])
        self.assertEqual(data["tso_hardiness"], "hardiness:4-7")
        self.assertEqual(data["tso_rhs"], "rhs:h7")
        self.assertEqual(data["tso_conservation"], "conservation:lc")

    def test_inline_labels_and_iucn_without_code(self):
        data = parse_tso_species(page("crawled_pages/tso/pages/articles_acer_acer-duplicatoserratum.html"))
        self.assertEqual(data["synonyms"], ["Acer palmatum var. pubescens"])     # "A. palmatum" expanded
        self.assertEqual(data["tso_distribution"], "TAIWAN.")
        self.assertEqual(data["tso_habitat"], "Deciduous forest between 1000 and 2000 m asl.")
        self.assertEqual(data["tso_hardiness"], "hardiness:6")
        self.assertEqual(data["tso_conservation"], "conservation:vu")         # "Vulnerable, due to ..."

    def test_bean_fractions(self):
        data = parse_tso_species(page("crawled_pages/tso/pages/articles_acacia_acacia-baileyana.html"))
        self.assertTrue(data["tso_description"].startswith("A small evergreen tree of slender graceful habit"))
        self.assertIn("Leaves bipinnate, 1 1/4 to 2 in. long", data["tso_description"])

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

    def test_species_page(self):
        data = parse_gardenia_plant(page("crawled_pages/gardenia/pages/plant_fagus-sylvatica.html"))
        self.assertEqual(species_key(data["name"]), ("fagus sylvatica", ""))
        self.assertEqual(data["title_common_names"], ["European Beech", "Common Beech"])
        self.assertEqual(data["gardenia_origin"], "Native to Central and Southern Europe.")
        self.assertEqual(data["gardenia_height"], "height:15.2m-18.3m")
        self.assertEqual(data["gardenia_spread"], "spread:10.7m-15.2m")
        self.assertEqual(data["gardenia_ph"], ["ph:acid", "ph:alkaline", "ph:neutral"])

    def test_latin_synonym_among_common_names(self):
        data = parse_gardenia_plant(page("crawled_pages/gardenia/pages/plant_quercus-robur.html"))
        self.assertEqual(data["title_common_names"][0], "English Oak")
        self.assertIn("Quercus pedunculata", data["title_common_names"])
        self.assertEqual(data["gardenia_hardiness"], "hardiness:5-8")
        self.assertEqual(data["gardenia_heat_zones"], "heat_zone:3-8")

    def test_conifer(self):
        data = parse_gardenia_plant(page("crawled_pages/gardenia/pages/plant_picea-abies.html"))
        self.assertEqual(data["gardenia_plant_type"], ["plant_type:conifers", "plant_type:trees"])
        self.assertTrue(is_tree_or_shrub(data["gardenia_plant_type"]))
        self.assertEqual(data["genus"], "Picea")
        self.assertEqual(data["gardenia_hardiness"], "hardiness:3-8")
        self.assertEqual(data["gardenia_heat_zones"], "heat_zone:1-8")
        self.assertEqual(data["gardenia_height"], "height:12.2m-18.3m")
        self.assertEqual(data["gardenia_ph"], ["ph:acid", "ph:neutral"])

    def test_perennial_is_skipped(self):
        html = page("crawled_pages/gardenia/pages/plant_mazus-reptans.html")
        self.assertEqual(plant_type(html), ["plant_type:perennials"])
        self.assertFalse(is_tree_or_shrub(plant_type(html)))
        data = parse_gardenia_plant(html)
        self.assertEqual(data["genus"], "")                     # the page has no Genus row
        self.assertEqual(data["gardenia_height"], "height:3cm-5cm")

    def test_trademark_name(self):
        data = parse_gardenia_plant(page("crawled_pages/gardenia/pages/plant_hydrangea-paniculata-quick-fire-fab.html"))
        self.assertEqual(data["name"], "Hydrangea paniculata Quick Fire Fab®")
        self.assertEqual(species_key(data["name"]), ("hydrangea paniculata", "Quick Fire Fab"))
        self.assertEqual(data["gardenia_plant_type"], ["plant_type:shrubs"])
        self.assertEqual(data["gardenia_height"], "height:180cm-240cm")

    def test_hybrid_cultivar(self):
        data = parse_gardenia_plant(page("crawled_pages/gardenia/pages/plant_caryopteris-x-clandonensis-kew-blue.html"))
        self.assertEqual(species_key(data["name"]), ("caryopteris × clandonensis", "Kew Blue"))
        self.assertEqual(data["common_names"], ["Blue Beard", "Bluebird"])
        self.assertEqual(data["gardenia_spread"], "spread:90cm-120cm")

    def test_variety(self):
        data = parse_gardenia_plant(page("crawled_pages/gardenia/pages/plant_pinus-mugo-var-pumilio.html"))
        self.assertEqual(species_key(data["name"]), ("pinus mugo var. pumilio", ""))
        self.assertEqual(data["gardenia_plant_type"], ["plant_type:conifers", "plant_type:shrubs"])
        self.assertEqual(data["gardenia_origin"], "Native to C Europe, Balkan Peninsula.")
        self.assertEqual(data["gardenia_spread"], "spread:180cm-3m")

    def test_without_heat_zones(self):
        data = parse_gardenia_plant(page("crawled_pages/gardenia/pages/plant_abies-fraseri.html"))
        self.assertEqual(data["common_names"], ["Fir", "Fraser Fir"])
        self.assertEqual(data["gardenia_hardiness"], "hardiness:4-7")
        self.assertEqual(data["gardenia_heat_zones"], "")
        self.assertEqual(data["gardenia_height"], "height:9.1m-15.2m")


if __name__ == "__main__":
    unittest.main()
