"""
Extractor: Trees and Shrubs Online + gardenia.net -> output/data/trees.jsonl

  1. TSO genus pages (/articles/<genus>/)        -> description of each genus
  2. TSO species pages (/articles/<genus>/<sp>/) -> one Tree each, keyed by the
     whole latin name ('fagus sylvatica', "abelia 'maurice foster'"), with the
     description of its genus
  3. gardenia plant pages, trees and shrubs only (Plant Type contains Trees,
     Shrubs or Conifers), joined to a Tree by
       the whole name  -> the same taxon as a TSO page
       the species     -> "Fagus sylvatica 'Pendula'" joins 'fagus sylvatica'
       a TSO synonym   -> the species under its accepted TSO name
     or a new Tree from gardenia only. The gardenia_* fields come from the page
     of the species itself; a cultivar page adds only its cultivar name and
     fills the fields only while the species page has not been seen.
  4. one Tree per line, sorted by key, and a summary of the run

Usage:
  python -m extractor.extractor              # all pages
  python -m extractor.extractor --limit 300  # only the first 300 pages of each source (trial)
"""

import argparse
import json
from collections import Counter
from dataclasses import fields
from pathlib import Path
from urllib.parse import urlparse

from extractor.extract_gardenia import is_tree_or_shrub, parse_gardenia_plant, plant_type, title_name
from extractor.extract_tso import parse_tso_genus, parse_tso_species
from extractor.tree import Tree, name_key, normalize_quotes, species_key

TSO_MANIFEST = Path("./crawled_pages/tso/manifest.json")
GARDENIA_MANIFEST = Path("./crawled_pages/gardenia/manifest.json")
OUT_PATH = Path("./output/data/trees.jsonl")
PROGRESS_EVERY = 500

GARDENIA_FIELDS = [f.name for f in fields(Tree) if f.name.startswith("gardenia_")]

STATS = Counter()


def load_manifest(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_page(entry: dict) -> str:
    path = Path(entry["saved_as"].replace("\\", "/"))
    return path.read_text(encoding="utf-8", errors="replace")


def tso_segments(url: str) -> list[str]:
    """Path segments after /articles/: ['fagus'] or ['fagus', 'fagus-sylvatica']."""
    return [seg for seg in urlparse(url).path.split("/") if seg][1:]


def progress(label: str, done: int, total: int):
    if done % PROGRESS_EVERY == 0 or done == total:
        print(f"  {label}: {done}/{total}", flush=True)


def species_name(latin: str, key: str) -> str:
    """The original spelling of the part of a latin name that forms the key:
    ("Fagus sylvatica 'Pendula'", 'fagus sylvatica') -> 'Fagus sylvatica'."""
    tokens = normalize_quotes(latin).replace("®", "").replace("™", "").split()
    tokens = ["×" if t.lower() in ("x", "×") else t for t in tokens]
    return " ".join(tokens[:len(key.split())])


def extract_tso(entries: list[dict]) -> dict[str, Tree]:
    genera, species = {}, []
    for entry in entries:
        segments = tso_segments(entry["url"])
        if len(segments) == 1 and len(segments[0]) > 1:     # skip the a-z listings
            genera[segments[0]] = parse_tso_genus(read_page(entry))
        elif len(segments) == 2:
            species.append(entry)
    STATS["tso genus pages"] = len(genera)
    STATS["tso species pages"] = len(species)

    trees = {}
    for done, entry in enumerate(species, 1):
        progress("tso species", done, len(species))
        data = parse_tso_species(read_page(entry))
        name = data.pop("name", "")
        key = name_key(name)
        if not key:
            STATS["tso pages without a name"] += 1
            continue
        if key in trees:
            # two articles of one taxon (salix-triandra, salix-triandra-1):
            # the second one only fills what the first one left empty
            STATS["tso pages with a duplicate name"] += 1
        tree = trees.setdefault(key, Tree(key=key, name=name, sources=["tso"]))
        tree.add_unique("urls", [entry["url"]])
        for list_name in ("common_names", "synonyms", "cultivars"):
            tree.add_unique(list_name, data.pop(list_name))
        data["tso_genus_description"] = genera.get(tso_segments(entry["url"])[0], "")
        for field_name, value in data.items():
            if not getattr(tree, field_name):
                setattr(tree, field_name, value)
    return trees


def synonym_index(trees: dict[str, Tree]) -> dict[str, str]:
    """species key of a TSO synonym -> key of its Tree. Synonyms that are a
    Tree themselves or belong to two Trees are left out."""
    index, ambiguous = {}, set()
    for tree in trees.values():
        for synonym in tree.synonyms:
            key = species_key(synonym)[0]
            if not key or key in trees:
                continue
            if key in index and index[key] != tree.key:
                ambiguous.add(key)
            index[key] = tree.key
    for key in ambiguous:
        del index[key]
    return index


def add_gardenia(trees: dict[str, Tree], entries: list[dict]):
    synonyms = synonym_index(trees)
    from_species_page = set()          # keys whose gardenia_* come from the species page
    from_cultivar_page = set()         # keys whose gardenia_* come from a cultivar page
    plants = [entry for entry in entries if entry.get("kind") == "plant"]
    STATS["gardenia plant pages"] = len(plants)

    for done, entry in enumerate(plants, 1):
        progress("gardenia plants", done, len(plants))
        html = read_page(entry)
        if not is_tree_or_shrub(plant_type(html)):
            STATS["gardenia skipped (not a tree or shrub)"] += 1
            name = title_name(html)
            if name_key(name) in trees or species_key(name)[0] in trees:
                STATS["gardenia skipped, but the name is in TSO"] += 1
            continue
        STATS["gardenia trees and shrubs"] += 1

        data = parse_gardenia_plant(html)
        name = data.pop("name")
        title_names = data.pop("title_common_names")
        whole = name_key(name)
        key, cultivar = species_key(name)
        if not key:
            STATS["gardenia pages without a name"] += 1
            continue

        if whole in trees:
            key, cultivar, how = whole, "", "the whole name"
        elif key in trees:
            how = "the species"
        elif key in synonyms:
            key, how = synonyms[key], "a TSO synonym"
        else:
            trees[key] = Tree(key=key, name=species_name(name, key))
            how = None
            STATS["gardenia pages starting a new tree"] += 1
        if how:
            target = "a TSO tree" if "tso" in trees[key].sources else "a gardenia tree"
            STATS[f"gardenia pages joined to {target} by {how}"] += 1
        tree = trees[key]
        is_species_page = not cultivar

        tree.add_unique("sources", ["gardenia"])
        tree.add_unique("urls", [entry["url"]])
        if cultivar:
            tree.add_unique("cultivars", [cultivar])
        genus = data["genus"] or tree.name.lstrip("× ").split()[0]
        tree.family = tree.family or data["family"]
        tree.genus = tree.genus or genus
        # the names under a cultivar's title name the cultivar ("European Beech 'Pendula'")
        names = (title_names if is_species_page else []) + data["common_names"]
        # gardenia lists old latin names among the common ones ("Quercus pedunculata")
        tree.add_unique("synonyms", [n for n in names if n.split()[0] == genus])
        tree.add_unique("common_names", [n for n in names if n.split()[0] != genus])

        if is_species_page and key not in from_species_page:
            from_species_page.add(key)
        elif not is_species_page and key not in from_species_page and key not in from_cultivar_page:
            from_cultivar_page.add(key)
        else:
            continue
        for field_name in GARDENIA_FIELDS:
            setattr(tree, field_name, data[field_name])

    STATS["gardenia_* fields from the species page"] = len(from_species_page)
    STATS["gardenia_* fields from a cultivar page"] = len(from_cultivar_page - from_species_page)


def write_trees(trees: dict[str, Tree]):
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as out:
        for key in sorted(trees):
            out.write(json.dumps(trees[key].to_dict(), ensure_ascii=False) + "\n")


def print_summary(trees: dict[str, Tree]):
    print("\nPages")
    for name, count in STATS.items():
        print(f"  {name:45} {count:6}")

    by_source = Counter(" + ".join(tree.sources) or "-" for tree in trees.values())
    print(f"\nTrees: {len(trees)}")
    for sources, count in by_source.most_common():
        print(f"  {sources:45} {count:6}")

    print("\nFilled fields (trees with a non-empty value)")
    for f in fields(Tree):
        filled = sum(1 for tree in trees.values() if getattr(tree, f.name))
        print(f"  {f.name:45} {filled:6}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="only the first N pages of each manifest")
    args = parser.parse_args()

    tso_entries = load_manifest(TSO_MANIFEST)[:args.limit]
    gardenia_entries = load_manifest(GARDENIA_MANIFEST)[:args.limit]

    print("Trees and Shrubs Online", flush=True)
    trees = extract_tso(tso_entries)
    print("gardenia.net", flush=True)
    add_gardenia(trees, gardenia_entries)

    write_trees(trees)
    print(f"\nWrote {len(trees)} trees to {OUT_PATH}")
    print_summary(trees)


if __name__ == "__main__":
    main()
