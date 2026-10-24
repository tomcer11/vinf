"""
Maps the gardenia.net plants onto Trees and Shrubs Online (TSO)

The project is about trees and shrubs, so TSO is the master list. gardenia.net
is a database of garden plants that also holds perennials, bulbs, grasses ...
Every gardenia plant is attached to the TSO page it belongs to, or left out.

Rules, the first one that applies wins:
  cultivar  the cultivar or variety has its own section on a TSO page:
            gardenia "Picea abies 'Acrocona'" -> TSO Picea abies, <h3 id=10731>'Acrocona'
            gardenia "Magnolia 'Butterflies'" -> TSO Magnolia Cultivars B, 'Butterflies'
            (also by the other names of a section: 'Weeping Blue' = 'Glauca Pendula')
  species   genus + species epithet (and hybrid sign) of a TSO species page:
            gardenia "Picea abies 'Little Gem'" -> TSO Picea abies
  synonym   genus + epithet of a synonym listed on a TSO page, or a synonym
            that gardenia lists among the common names of the plant:
            gardenia "Picea excelsa" -> TSO Picea abies
            gardenia "Potentilla fruticosa 'Abbotswood'" -> TSO Dasiphora fruticosa
  genus     only the genus has a TSO page. Accepted only when gardenia calls
            the plant woody (Plant Type Trees, Shrubs, Conifers ...), so that
            herbaceous Salvia or Iris do not get into an index of woody plants
  (none)    not a TSO tree or shrub, left out

Input:  data/tso.jsonl, data/gardenia.jsonl   (written by extractor.py)
Output: data/trees.jsonl   one document per TSO page, with the gardenia
                           plants mapped to it in "gardenia"
        data/mapping.csv   one line per gardenia plant and how it was mapped

Usage:
  python mapping.py
"""

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from extractor import DATA_DIR, GARDENIA_OUT, MISAPPLIED_RE, TSO_OUT, parse_sci_name

TREES_OUT = DATA_DIR / "trees.jsonl"
MAPPING_CSV = DATA_DIR / "mapping.csv"

# gardenia "Plant Type" values of woody plants. "Fruits" is left out: it also
# holds strawberries and melons; fruit trees are tagged "Trees" as well
WOODY_TYPES = {"trees", "shrubs", "conifers", "climbers", "roses", "palms - cycads", "bamboos"}

# gardenia fields kept in the merged document
GARDENIA_KEEP = [
    "url", "title", "scientific_name", "common_names", "plant_type", "hardiness", "usda",
    "heat_zones", "exposure", "height", "spread", "maintenance", "water_needs",
    "soil_type", "soil_ph", "soil_drainage", "characteristics", "tolerances", "attracts",
    "garden_uses", "garden_styles", "toxic_humans", "toxic_cats", "toxic_dogs",
    "toxic_horses", "native_to", "award_agm", "pests", "pest_evidence", "pest_free",
    "pest_sentences", "habitat_sentences", "scientific_synonyms", "description",
]

TRADEMARK_RE = re.compile(r"[®™]|\(r\)")
SPACES_RE = re.compile(r"\s+")
QUOTES_RE = re.compile(r"""['‘’"]""")


def norm_cultivar(name: str) -> str:
    """'Little Gem', ‘Little Gem’, LITTLE GEM® -> 'little gem'"""
    name = TRADEMARK_RE.sub("", QUOTES_RE.sub("", name or "")).lower()
    return SPACES_RE.sub(" ", name).strip()


def species_key(genus: str | None, epithet: str | None, hybrid: bool = False) -> str | None:
    if not genus or not epithet:
        return None
    return f"{genus} {'x ' if hybrid else ''}{epithet}"


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class TsoLookup:
    """Name -> TSO page lookups built from the TSO records."""

    def __init__(self, tso: list[dict]):
        self.species = {}            # "picea abies" -> page index
        self.synonyms = {}           # "picea excelsa" -> page index
        self.genera = {}             # "picea" -> genus page index
        self.cultivars = {}          # ("picea", "abies", "acrocona") -> (page, anchor)
        self.genus_cultivars = defaultdict(list)   # ("magnolia", "butterflies") -> [(page, anchor)]

        for i, rec in enumerate(tso):
            name = rec.get("name") or {}
            genus = name.get("genus")
            if rec["kind"] == "genus":
                if genus:
                    self.genera.setdefault(genus, i)
                continue
            key = species_key(genus, name.get("epithet"), name.get("hybrid"))
            # the shortest title wins: "Picea likiangensis" over
            # "Picea likiangensis aggregate", "Cornus florida" over "Cornus florida Cultivars A-G"
            if key and not name.get("cultivar"):
                best = self.species.get(key)
                if best is None or len(rec["title"].split()) < len(tso[best]["title"].split()):
                    self.species[key] = i
            if name.get("cultivar"):           # page about one cultivar: "Acer 'Cascade'"
                self._add_cultivar(genus, name.get("epithet"), name["cultivar"], i, None)
            for syn in rec.get("synonyms", []):
                if MISAPPLIED_RE.search(syn):
                    continue
                parts = parse_sci_name(syn)
                syn_key = species_key(parts.get("genus"), parts.get("epithet"), parts.get("hybrid"))
                if syn_key and not parts.get("infra"):
                    self.synonyms.setdefault(syn_key, i)
            for section in rec.get("sections", []):
                section_name = section["name"]
                infra = re.match(r"(?:subsp\.|var\.|f\.)\s+([a-z-]+)", section_name)
                label = infra.group(1) if infra else section_name
                self._add_cultivar(genus, name.get("epithet"), label, i, section["id"])
                for other in section.get("synonyms", []):
                    parts = parse_sci_name(other)
                    other_label = parts.get("cultivar") or parts.get("infra")
                    if other_label:
                        self._add_cultivar(genus, name.get("epithet"), other_label, i, section["id"])

    def _add_cultivar(self, genus, epithet, label, page, anchor):
        label = norm_cultivar(label)
        if not genus or not label:
            return
        self.cultivars.setdefault((genus, epithet, label), (page, anchor))
        self.genus_cultivars[(genus, label)].append((page, anchor))

    def match(self, plant: dict) -> tuple[str, int | None, str | None]:
        """(level, TSO page index, section anchor) for one gardenia record."""
        name = plant.get("name") or {}
        genus = name.get("genus")
        if not genus:
            return "none", None, None
        epithet = name.get("epithet")
        hybrid = bool(name.get("hybrid"))
        cultivar = norm_cultivar(name.get("cultivar") or name.get("infra") or "")

        if cultivar:
            hit = self.cultivars.get((genus, epithet, cultivar))
            if hit is None and not epithet:
                pages = self.genus_cultivars.get((genus, cultivar), [])
                if len({p for p, _ in pages}) == 1:   # only when unambiguous
                    hit = pages[0]
            if hit is not None:
                return "cultivar", hit[0], hit[1]

        for key in (species_key(genus, epithet, hybrid), species_key(genus, epithet, not hybrid)):
            if key in self.species:
                return "species", self.species[key], None
        for key in (species_key(genus, epithet, hybrid), species_key(genus, epithet, not hybrid)):
            if key in self.synonyms:
                return "synonym", self.synonyms[key], None
        # another name of the plant that gardenia gives among its common names
        for other in plant.get("scientific_synonyms") or []:
            parts = parse_sci_name(other)
            key = species_key(parts.get("genus"), parts.get("epithet"), parts.get("hybrid"))
            for index in (self.species, self.synonyms):
                if key in index:
                    return "synonym", index[key], None

        if genus in self.genera and is_woody(plant):
            return "genus", self.genera[genus], None
        return "none", None, None


def is_woody(plant: dict) -> bool:
    return any(t.lower() in WOODY_TYPES for t in plant.get("plant_type", []))


def merge_zones(zones: list[dict]) -> dict | None:
    """Union of USDA ranges; a single TSO value only gives the minimum."""
    zones = [z for z in zones if z]
    if not zones:
        return None
    highs = [z["max"] for z in zones if z.get("max") is not None]
    return {"min": min(z["min"] for z in zones), "max": max(highs) if highs else None}


def build():
    tso = load_jsonl(TSO_OUT)
    gardenia = load_jsonl(GARDENIA_OUT)
    lookup = TsoLookup(tso)

    # a scientific synonym of gardenia must start with a known genus, else it
    # is a common name like "Sweet pecan"
    known_genera = {(r.get("name") or {}).get("genus") for r in tso + gardenia} - {None}
    for plant in gardenia:
        plant["scientific_synonyms"] = [
            s for s in plant.get("scientific_synonyms", [])
            if parse_sci_name(s).get("genus") in known_genera]

    attached = defaultdict(list)
    levels = Counter()
    rows = []
    for plant in gardenia:
        level, page, anchor = lookup.match(plant)
        levels[level] += 1
        rows.append({
            "gardenia_url": plant["url"],
            "gardenia_title": plant["title"],
            "plant_type": ", ".join(plant.get("plant_type", [])),
            "woody": is_woody(plant),
            "level": level,
            "tso_title": tso[page]["title"] if page is not None else "",
            "tso_url": (tso[page]["url"] + (f"#{anchor}" if anchor else "")) if page is not None else "",
        })
        if page is not None:
            entry = {key: plant.get(key) for key in GARDENIA_KEEP}
            entry["match"] = level
            entry["tso_anchor"] = anchor
            attached[page].append(entry)

    DATA_DIR.mkdir(exist_ok=True)
    with TREES_OUT.open("w", encoding="utf-8") as f:
        for i, rec in enumerate(tso):
            plants = attached.get(i, [])
            rec["gardenia"] = plants
            rec["zones"] = merge_zones([rec.get("usda")] + [p.get("usda") for p in plants])
            rec["all_pests"] = sorted(set(rec["pests"]).union(*(p["pests"] or [] for p in plants)))
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    with MAPPING_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    mapped = sum(n for level, n in levels.items() if level != "none")
    woody_unmapped = sum(1 for r in rows if r["level"] == "none" and r["woody"])
    with_gardenia = sum(1 for plants in attached.values() if plants)
    print("--- gardenia -> TSO mapping ---")
    print(f"  gardenia plants          : {len(gardenia)}")
    for level in ("cultivar", "species", "synonym", "genus", "none"):
        print(f"  {level:<24} : {levels[level]}")
    print(f"  mapped in total          : {mapped} ({100 * mapped / max(1, len(gardenia)):.1f} %)")
    print(f"  woody but not in TSO     : {woody_unmapped}")
    print(f"  TSO pages with gardenia  : {with_gardenia} of {len(tso)}")
    print(f"  -> {TREES_OUT}, {MAPPING_CSV}")
    return levels


if __name__ == "__main__":
    build()
