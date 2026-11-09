"""
Tests of the wikitext regexes on snippets copied from real articles of the dump.

  python -m unittest tests.test_wikitext
"""

import unittest

from wiki.wikitext import (clean_wikitext, common_names, conservation, join_key, latin_name, parse_article,
                           render_templates, section_attributes, lead_and_sections, synonym_names, taxobox,
                           title_key)

KALMIA = """{{Short description|Species of plant}}
{{Redirect|Calico bush|the Rachel Field novel|Calico Bush (novel)}}
{{Speciesbox
| image = Kalmia_Latifolia.jpg
| status = LC
| status_system = IUCN3.1
| status_ref = <ref>{{cite iucn |author=Stritch, L. |date=2018 |title=''Kalmia latifolia'' |volume=2018}}</ref>
| genus = Kalmia
| species = latifolia
| authority = [[Carl Linnaeus|L.]]
| range_map = Kalmia latifolia map.png
}}

'''''Kalmia latifolia''''', the '''mountain laurel''',<ref name=GRIN>{{GRIN | access-date = 12 December 2017}}</ref> '''calico-bush''',<ref name=GRIN/> or '''spoonwood''',<ref name=GRIN/> is a [[flowering plant]] in the family [[Ericaceae]]. It is native to the [[eastern United States]].

== Description ==
[[File:Kalmia latifolia flowers.jpg|thumb|Flowers of a [[cultivar]]]]
''Kalmia latifolia'' is an evergreen shrub growing {{convert|3|-|9|m|ft}} tall.<ref>{{cite web|url=x}}</ref>

== Distribution and habitat ==
The plant is naturally found on rocky slopes.<!-- citation needed -->

=== Soils ===
It thrives in acid soil.

== Uses ==
* Wood for spoons
* {{nowrap|Ornamental [[shrub]]}}

== References ==
{{Reflist}}

[[Category:Kalmia]]
[[Category:Trees of Northern America]]
"""


class Cleaning(unittest.TestCase):
    def test_links(self):
        self.assertEqual(clean_wikitext("a [[flowering plant]] of the [[Ericaceae|heath family]]"),
                         "a flowering plant of the heath family")

    def test_files_and_categories_are_dropped(self):
        self.assertEqual(clean_wikitext("[[File:x.jpg|thumb|A [[tree]] in snow]]Text[[Category:Trees]]"), "Text")

    def test_refs_comments_and_quotes(self):
        text = "'''Fagus''' is a genus<ref name=a>{{cite web|url=x}}</ref><ref name=a/> of trees.<!-- note -->"
        self.assertEqual(clean_wikitext(text), "Fagus is a genus of trees.")

    def test_nested_templates_from_the_inside_out(self):
        self.assertEqual(render_templates("{{nowrap|{{convert|10|m|ft}}}} tall{{citation needed|date=May 2020}}"),
                         "10 m tall")

    def test_convert_range(self):
        self.assertEqual(clean_wikitext("{{convert|20|–|30|m|ft|abbr=on}}"), "20–30 m")
        self.assertEqual(clean_wikitext("{{convert|20|to|30|m}}"), "20 to 30 m")

    def test_lists_and_headings(self):
        self.assertEqual(clean_wikitext("=== Wood ===\n* hard\n* heavy"), "hard\nheavy")

    def test_tables_are_dropped(self):
        self.assertEqual(clean_wikitext("Before\n{| class=wikitable\n|-\n| a || b\n|}\nAfter"), "Before\nAfter")

    def test_external_links(self):
        self.assertEqual(clean_wikitext("see [https://example.org the site] and [https://example.org]"),
                         "see the site and")


class Taxobox(unittest.TestCase):
    def test_speciesbox_parameters(self):
        box, params = taxobox(KALMIA)
        self.assertEqual(box, "speciesbox")
        self.assertEqual(params["genus"], "Kalmia")
        self.assertEqual(params["authority"], "[[Carl Linnaeus|L.]]")
        self.assertIn("{{cite iucn", params["status_ref"])     # pipes of nested templates do not split

    def test_latin_name_from_genus_and_species(self):
        self.assertEqual(latin_name(taxobox(KALMIA)[1]), "Kalmia latifolia")

    def test_latin_name_infraspecific(self):
        text = "{{Infraspeciesbox\n| genus = Pseudotsuga\n| species = menziesii\n| varietas = glauca\n}}"
        self.assertEqual(latin_name(taxobox(text)[1]), "Pseudotsuga menziesii var. glauca")
        text = "{{Infraspeciesbox\n|genus = Olea\n|species = europaea\n|subspecies = europaea\n}}"
        self.assertEqual(latin_name(taxobox(text)[1]), "Olea europaea subsp. europaea")

    def test_latin_name_from_taxon(self):
        self.assertEqual(latin_name(taxobox("{{Automatic taxobox\n| taxon = Acer\n}}")[1]), "Acer")
        self.assertEqual(latin_name(taxobox("{{Speciesbox | taxon = ''Platanus'' × ''hispanica''}}")[1]),
                         "Platanus × hispanica")

    def test_latin_name_without_disambiguation_of_the_genus(self):
        text = "{{Speciesbox\n| genus = Sasa (plant)\n| species = veitchii\n}}"
        self.assertEqual(latin_name(taxobox(text)[1]), "Sasa veitchii")

    def test_no_taxobox(self):
        self.assertEqual(taxobox("{{Infobox person|name=X}}"), ("", {}))

    def test_synonyms_species_list(self):
        value = "{{Species list\n|Abies menziesii |Mirb.\n|Pseudotsuga taxifolia var. viridis |ined.}}"
        self.assertEqual(synonym_names(value), ["Abies menziesii", "Pseudotsuga taxifolia var. viridis"])

    def test_synonyms_bullet_list(self):
        value = "\n* ''Pseudotsuga menziesii'' var. ''caesia'' (Schwer.) Franco\n* ''Abies'' Mill.<br />"
        self.assertEqual(synonym_names(value), ["Pseudotsuga menziesii var. caesia"])

    def test_conservation(self):
        self.assertEqual(conservation({"status": "LC", "status_system": "IUCN3.1"}), "conservation:lc")
        self.assertEqual(conservation({"status": "LR/nt", "status_system": "IUCN2.3"}), "conservation:lr")
        self.assertEqual(conservation({"status": "G5", "status_system": "TNC"}), "")


class Keys(unittest.TestCase):
    def test_join_key(self):
        self.assertEqual(join_key("Fagus sylvatica"), "fagus sylvatica")
        self.assertEqual(join_key("Platanus x hispanica"), "platanus × hispanica")
        self.assertEqual(join_key("Platanus ×hispanica"), "platanus × hispanica")
        self.assertEqual(join_key("Pinus mugo ssp. uncinata"), "pinus mugo subsp. uncinata")

    def test_title_key_drops_disambiguation(self):
        self.assertEqual(title_key("Magnolia (plant)"), "magnolia")


class Article(unittest.TestCase):
    def test_sections_by_attribute(self):
        _, sections = lead_and_sections(KALMIA)
        self.assertEqual([h for h, _ in sections], ["Description", "Distribution and habitat", "Uses", "References"])
        found = section_attributes(sections)
        self.assertEqual(found["description"], "Kalmia latifolia is an evergreen shrub growing 3-9 m tall.")
        self.assertEqual(found["distribution"], "The plant is naturally found on rocky slopes.\nIt thrives in acid soil.")
        self.assertEqual(found["uses"], "Wood for spoons\nOrnamental shrub")
        self.assertEqual(found["ecology"], "")

    def test_common_names(self):
        lead = "'''''Pseudotsuga menziesii'' var. ''glauca''''', or '''Rocky Mountain Douglas-fir''', is"
        self.assertEqual(common_names("Pseudotsuga menziesii var. glauca", "", lead, "Pseudotsuga menziesii var. glauca"),
                         ["Rocky Mountain Douglas-fir"])
        self.assertEqual(common_names("Douglas fir", "", "The '''Douglas fir''' (''Pseudotsuga'')", "Pseudotsuga menziesii"),
                         ["Douglas fir"])

    def test_parse_article(self):
        escaped = KALMIA.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        article = parse_article("Kalmia latifolia", escaped)
        self.assertEqual(article["latin_key"], "kalmia latifolia")
        self.assertEqual(article["title_key"], "kalmia latifolia")
        self.assertEqual(article["authority"], "L.")
        self.assertEqual(article["status"], "conservation:lc")
        self.assertEqual(article["common_names"], ["mountain laurel", "calico-bush", "spoonwood"])
        self.assertEqual(article["lead"], "Kalmia latifolia, the mountain laurel, calico-bush, or spoonwood, is a "
                                          "flowering plant in the family Ericaceae. It is native to the eastern United States.")
        self.assertEqual(article["categories"], ["Kalmia", "Trees of Northern America"])


if __name__ == "__main__":
    unittest.main()
