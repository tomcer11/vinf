"""
Spark job: Trees and Shrubs Online + gardenia.net -> one Tree per species.

The Spark version of extractor/extractor.py with the same output. The regex
parsers of the first submission (extractor/extract_tso.py,
extractor/extract_gardenia.py) run unchanged as Python UDFs; the loops and
dicts of the old extractor became Spark operations:

  manifest.json         from_json + posexplode: one row per entry, pos = order in the manifest
  saved HTML            read.text(wholetext) + input_file_name, LEFT JOIN with the manifest
  TSO genus pages       UDF parse_tso_genus, JOIN to the species by the first URL segment
  TSO duplicate names   GROUP BY key (salix-triandra, salix-triandra-1): first non-empty
                        value in manifest order
  gardenia -> Tree      three LEFT JOINs (whole name, species, TSO synonym) + CASE WHEN
  gardenia per Tree     GROUP BY tree key: names and cultivars in manifest order, the
                        gardenia_* fields of the species page (else of the first cultivar)
  TSO + gardenia        FULL OUTER JOIN on key

The old code depended on the order of the pages ("the first page wins"); a
Spark group has no order, so every "first" is taken explicitly by pos
(sort_array of (pos, value) structs).

Usage (in the container, from /work):
  python -m spark_jobs.extract_trees
  python -m spark_jobs.extract_trees --compare output/data/trees.jsonl   # check against the old extractor
"""

import argparse
import os
import time
from dataclasses import fields

from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType, BooleanType, StringType, StructField, StructType
from pyspark.sql.window import Window

from extractor.extract_gardenia import is_tree_or_shrub, parse_gardenia_plant, plant_type, title_name
from extractor.extract_tso import parse_tso_genus, parse_tso_species
from extractor.extractor import species_name
from extractor.tree import Tree, name_key, species_key
from spark_jobs.session import get_spark

TSO_MANIFEST = "crawled_pages/tso/manifest.json"
TSO_PAGES = "crawled_pages/tso/pages"
GARDENIA_MANIFEST = "crawled_pages/gardenia/manifest.json"
GARDENIA_PAGES = "crawled_pages/gardenia/pages"
OUT = "output/spark/trees"
STATS_OUT = "output/spark/extract_trees_stats.tsv"

TREE_FIELDS = [f.name for f in fields(Tree)]
LIST_FIELDS = [f.name for f in fields(Tree) if f.type == list[str]]
GARDENIA_FIELDS = [name for name in TREE_FIELDS if name.startswith("gardenia_")]
TSO_TEXT_FIELDS = ["family", "genus", "tso_authors", "tso_description", "tso_genus_description",
                   "tso_distribution", "tso_habitat", "tso_hardiness", "tso_rhs", "tso_conservation"]
NAME_LISTS = ["common_names", "synonyms", "cultivars"]

STRINGS = ArrayType(StringType())
MANIFEST_SCHEMA = ArrayType(StructType([
    StructField("url", StringType()),
    StructField("kind", StringType()),
    StructField("saved_as", StringType()),
]))


def struct_of(names: list[str], extra: list[StructField] = ()) -> StructType:
    return StructType([StructField(n, STRINGS if n in LIST_FIELDS else StringType()) for n in names] + list(extra))


TSO_SPECIES_SCHEMA = struct_of(["key", "name"] + TSO_TEXT_FIELDS[:2] + NAME_LISTS + TSO_TEXT_FIELDS[2:])
GARDENIA_SCHEMA = struct_of(
    ["name", "whole", "key", "cultivar", "family", "genus", "common_names"] + GARDENIA_FIELDS,
    [StructField("is_tree", BooleanType()), StructField("title_common_names", STRINGS)],
)


# === UDFs: the regex parsers of the first submission ================================

@F.udf(TSO_SPECIES_SCHEMA)
def tso_species_udf(html):
    data = parse_tso_species(html)
    data.setdefault("name", "")
    data.setdefault("tso_authors", "")
    data["key"] = name_key(data["name"])
    return data


@F.udf(StringType())
def tso_genus_udf(html):
    return parse_tso_genus(html)


@F.udf(GARDENIA_SCHEMA)
def gardenia_udf(html):
    """All fields of a tree or shrub page; only the name of the other plants."""
    if not is_tree_or_shrub(plant_type(html)):
        name = title_name(html)
        return {"is_tree": False, "name": name, "whole": name_key(name), "key": species_key(name)[0]}
    data = parse_gardenia_plant(html)
    data["is_tree"] = True
    data["whole"] = name_key(data["name"])
    data["key"], data["cultivar"] = species_key(data["name"])
    return data


species_key_udf = F.udf(lambda name: species_key(name)[0], StringType())
species_name_udf = F.udf(species_name, StringType())


# === helpers: "the first" and "add_unique" without a row order ========================

def by_pos(*columns):
    """collect_list of (pos, columns...) sorted by pos: the rows of a group in manifest order."""
    return F.sort_array(F.collect_list(F.struct("pos", *columns)))


def first_nonempty(column: str):
    """The first non-empty value of a group in manifest order ('' if none)."""
    values = F.filter(by_pos(F.col(column).alias("v")), lambda x: x["v"] != "")
    return F.coalesce(F.element_at(values, 1)["v"], F.lit(""))


def concat_lists(column: str):
    """The lists of a group concatenated in manifest order."""
    return F.flatten(F.transform(by_pos(F.col(column).alias("v")), lambda x: x["v"]))


def unique_ci(array):
    """Tree.add_unique: drop empty values and case-insensitive repeats, keep the first spelling."""
    def add(acc, x):
        seen = F.exists(acc, lambda y: F.lower(y) == F.lower(x))
        return F.when(x.isNull() | (x == "") | seen, acc).otherwise(F.concat(acc, F.array(x)))
    return F.aggregate(array, F.array().cast(STRINGS), add)


def or_empty_list(column):
    return F.coalesce(column, F.array().cast(STRINGS))


# === loading ================================================================

def load_manifest(spark, path: str, source: str):
    """One row per manifest entry: pos (order in the file), url, kind, file name."""
    entries = F.posexplode(F.from_json("value", MANIFEST_SCHEMA))
    return (spark.read.text(path, wholetext=True)
            .select(entries.alias("pos", "entry"))
            .select("pos", "entry.url", "entry.kind",
                    F.regexp_extract("entry.saved_as", r"([^\\/]+)$", 1).alias("file"))
            .withColumn("source", F.lit(source)))


def load_pages(spark, manifest, pages_dir: str):
    """Manifest entries with the HTML of their saved file.

    The directory is read as a whole and filtered by pathGlobFilter: a glob
    ('pages/*.html') or a list of 10k paths makes Spark list every path in a
    task of its own. The manifest (small) is broadcast, so the HTML is not
    shuffled for the join."""
    files = (spark.read.option("pathGlobFilter", "*.html")
             .text(pages_dir, wholetext=True)
             .select(F.regexp_extract(F.input_file_name(), r"([^/]+)$", 1).alias("file"),
                     F.col("value").alias("html")))
    return files.join(F.broadcast(manifest), "file")


def missing_files(spark, manifest, pages_dir: str) -> int:
    """Manifest entries without a saved file; compares names only, no HTML is read."""
    on_disk = spark.createDataFrame([(name,) for name in os.listdir(pages_dir)], "file string")
    return manifest.join(on_disk, "file", "left_anti").count()


# === Trees and Shrubs Online ==================================================

def extract_tso(pages, stats: dict):
    """One row per TSO tree, the columns of Tree that TSO fills."""
    segments = F.split(F.regexp_extract("url", r"/articles/(.+?)/?$", 1), "/")
    pages = pages.withColumn("segments", segments)

    # genus pages (/articles/fagus/); /articles/a/ are the a-z listings
    genus_pages = pages.filter((F.size("segments") == 1) & (F.length(F.col("segments")[0]) > 1))
    genera = (genus_pages
              .select(F.col("segments")[0].alias("genus_segment"), "pos", tso_genus_udf("html").alias("text"))
              .groupBy("genus_segment")
              .agg(F.max_by("text", "pos").alias("tso_genus_description"))
              .cache())

    parsed = (pages.filter(F.size("segments") == 2)
              .select("pos", "url", F.col("segments")[0].alias("genus_segment"),
                      tso_species_udf("html").alias("data"))
              .select("pos", "url", "genus_segment", "data.*")
              .cache())
    stats["tso genus pages"] = genera.count()
    stats["tso species pages"] = parsed.count()
    stats["tso pages without a name"] = parsed.filter(F.col("key") == "").count()

    species = (parsed.filter(F.col("key") != "")
               .drop("tso_genus_description")
               .join(F.broadcast(genera), "genus_segment", "left")
               .withColumn("tso_genus_description", F.coalesce("tso_genus_description", F.lit(""))))

    # two articles of one taxon: the second one only fills what the first one left empty
    trees = species.groupBy("key").agg(
        F.element_at(by_pos("name"), 1)["name"].alias("name"),
        unique_ci(F.transform(by_pos("url"), lambda x: x["url"])).alias("urls"),
        *[unique_ci(concat_lists(c)).alias(c) for c in NAME_LISTS],
        *[first_nonempty(c).alias(c) for c in TSO_TEXT_FIELDS],
        F.count(F.lit(1)).alias("pages"),
    )
    trees = trees.cache()
    stats["tso pages with a duplicate name"] = trees.agg(F.sum(F.col("pages") - 1)).first()[0]
    parsed.unpersist()
    return trees.drop("pages")


def synonym_index(tso_trees):
    """species key of a TSO synonym -> key of its Tree. Synonyms that are a Tree
    themselves or belong to two Trees are left out."""
    synonyms = (tso_trees
                .select(F.col("key").alias("target"), F.explode("synonyms").alias("synonym"))
                .withColumn("synonym_key", species_key_udf("synonym"))
                .filter(F.col("synonym_key") != ""))
    synonyms = synonyms.join(tso_trees.select(F.col("key").alias("synonym_key")), "synonym_key", "left_anti")
    return (synonyms.groupBy("synonym_key")
            .agg(F.countDistinct("target").alias("trees"), F.first("target").alias("target"))
            .filter(F.col("trees") == 1)
            .select(F.col("synonym_key").alias("key"), F.col("target").alias("synonym_target")))


# === gardenia.net =============================================================

def gardenia_pages(pages, tso_trees, stats: dict):
    """Gardenia tree and shrub pages, each assigned to the key of its Tree."""
    plants = (pages
              .select("pos", "url", gardenia_udf("html").alias("data"))
              .select("pos", "url", "data.*"))
    plants = plants.cache()
    tso_keys = tso_trees.select("key")
    whole_in_tso = tso_keys.select(F.col("key").alias("whole"), F.lit(True).alias("whole_in_tso"))
    key_in_tso = tso_keys.select("key", F.lit(True).alias("key_in_tso"))
    with_tso_flags = lambda df: df.join(whole_in_tso, "whole", "left").join(key_in_tso, "key", "left")

    skipped = plants.filter(~F.col("is_tree"))
    stats["gardenia plant pages"] = plants.count()
    stats["gardenia skipped (not a tree or shrub)"] = skipped.count()
    stats["gardenia skipped, but the name is in TSO"] = (
        with_tso_flags(skipped).filter(F.col("whole_in_tso") | F.col("key_in_tso")).count())

    trees_pages = plants.filter(F.col("is_tree"))
    stats["gardenia trees and shrubs"] = trees_pages.count()
    stats["gardenia pages without a name"] = trees_pages.filter(F.col("key") == "").count()
    trees_pages = trees_pages.filter(F.col("key") != "")

    # whole name > species > TSO synonym > a new tree from gardenia only
    resolved = with_tso_flags(trees_pages).join(F.broadcast(synonym_index(tso_trees)), "key", "left")
    how = (F.when(F.col("whole_in_tso"), "the whole name")
            .when(F.col("key_in_tso"), "the species")
            .when(F.col("synonym_target").isNotNull(), "a TSO synonym")
            .otherwise("new"))
    resolved = (resolved.withColumn("how", how)
                .withColumn("tree_key", F.when(F.col("how") == "the whole name", F.col("whole"))
                                         .when(F.col("how") == "a TSO synonym", F.col("synonym_target"))
                                         .otherwise(F.col("key")))
                .withColumn("cultivar", F.when(F.col("how") == "the whole name", "").otherwise(F.col("cultivar"))))
    return resolved.cache()


def gardenia_stats(resolved, stats: dict):
    for how, count in resolved.filter(F.col("how") != "new").groupBy("how").count().collect():
        stats[f"gardenia pages joined to a TSO tree by {how}"] = count
    # pages of a gardenia-only tree: the first one starts it, the others join it
    new = resolved.filter(F.col("how") == "new").withColumn(
        "first", F.col("pos") == F.min("pos").over(Window.partitionBy("tree_key")))
    stats["gardenia pages starting a new tree"] = new.filter("first").count()
    stats["gardenia pages joined to a gardenia tree by the whole name"] = new.filter(
        ~F.col("first") & (F.col("whole") == F.col("tree_key"))).count()
    stats["gardenia pages joined to a gardenia tree by the species"] = new.filter(
        ~F.col("first") & (F.col("whole") != F.col("tree_key"))).count()


def aggregate_gardenia(resolved, tso_trees):
    """One row per tree key with everything gardenia adds to it."""
    # name of a gardenia-only tree: the species part of its first page's name
    new_names = (resolved.filter(F.col("how") == "new")
                 .groupBy("tree_key")
                 .agg(F.min_by("name", "pos").alias("first_name"))
                 .select("tree_key", species_name_udf("first_name", "tree_key").alias("tree_name")))
    tree_names = tso_trees.select(F.col("key").alias("tree_key"), F.col("name").alias("tree_name")).union(new_names)

    pages = resolved.join(tree_names, "tree_key")
    name_genus = F.split(F.regexp_replace("tree_name", r"^[× ]+", ""), " ")[0]
    pages = pages.withColumn("page_genus", F.when(F.col("genus") != "", F.col("genus")).otherwise(name_genus))
    # the names under a cultivar's title name the cultivar ("European Beech 'Pendula'");
    # gardenia lists old latin names among the common ones ("Quercus pedunculata")
    is_species_page = F.col("cultivar") == ""
    names = F.concat(F.when(is_species_page, F.col("title_common_names")).otherwise(F.array().cast(STRINGS)),
                     F.col("common_names"))
    first_word = lambda n: F.split(F.trim(n), r"\s+")[0]
    pages = (pages
             .withColumn("names_synonyms", F.filter(names, lambda n: first_word(n) == F.col("page_genus")))
             .withColumn("names_common", F.filter(names, lambda n: first_word(n) != F.col("page_genus")))
             .withColumn("cultivars", F.when(is_species_page, F.array().cast(STRINGS))
                                       .otherwise(F.array("cultivar")))
             .withColumn("fields", F.struct(*GARDENIA_FIELDS)))

    # gardenia_* come from the species page; from the first cultivar page only when there is none
    gardenia_fields = F.sort_array(F.collect_list(F.struct((~is_species_page).alias("cultivar_page"), "pos", "fields")))
    return pages.groupBy(F.col("tree_key").alias("key")).agg(
        F.first("tree_name").alias("g_name"),
        F.transform(by_pos("url"), lambda x: x["url"]).alias("g_urls"),
        first_nonempty("family").alias("g_family"),
        F.element_at(by_pos("page_genus"), 1)["page_genus"].alias("g_genus"),
        concat_lists("names_common").alias("g_common_names"),
        concat_lists("names_synonyms").alias("g_synonyms"),
        concat_lists("cultivars").alias("g_cultivars"),
        F.element_at(gardenia_fields, 1)["fields"].alias("g_fields"),
    )


# === TSO + gardenia ==========================================================

def merge(tso_trees, gardenia):
    """FULL OUTER JOIN on key; TSO values first, gardenia fills and appends."""
    t = tso_trees.withColumn("in_tso", F.lit(True))
    g = gardenia.withColumn("in_gardenia", F.lit(True))
    joined = t.join(g, "key", "full_outer")
    nonempty = lambda column: F.when(F.col(column) != "", F.col(column))
    columns = {
        "key": F.col("key"),
        "name": F.coalesce("name", "g_name"),
        "sources": F.concat(F.when(F.col("in_tso"), F.array(F.lit("tso"))).otherwise(F.array().cast(STRINGS)),
                            F.when(F.col("in_gardenia"), F.array(F.lit("gardenia"))).otherwise(F.array().cast(STRINGS))),
        "urls": unique_ci(F.concat(or_empty_list(F.col("urls")), or_empty_list(F.col("g_urls")))),
        "family": F.coalesce(nonempty("family"), F.col("g_family"), F.lit("")),
        "genus": F.coalesce(nonempty("genus"), F.col("g_genus"), F.lit("")),
    }
    for name in NAME_LISTS:
        columns[name] = unique_ci(F.concat(or_empty_list(F.col(name)), or_empty_list(F.col(f"g_{name}"))))
    for name in TSO_TEXT_FIELDS[2:]:
        columns[name] = F.coalesce(F.col(name), F.lit(""))
    for name in GARDENIA_FIELDS:
        empty = F.array().cast(STRINGS) if name in LIST_FIELDS else F.lit("")
        columns[name] = F.coalesce(F.col(f"g_fields.{name}"), empty)
    return joined.select(*[columns[name].alias(name) for name in TREE_FIELDS])


def tree_stats(trees, stats: dict):
    stats["trees"] = trees.count()
    for sources, count in trees.groupBy(F.array_join("sources", " + ").alias("s")).count().orderBy("s").collect():
        stats[f"trees from {sources}"] = count


def compare(spark, trees, old_path: str) -> dict:
    """Trees missing / added / different against the output of the old extractor."""
    old = spark.read.schema(trees.schema).json(old_path)
    joined = old.alias("old").join(trees.alias("new"), "key", "full_outer")
    result = {
        "compare: trees only in the old output": joined.filter(F.col("new.name").isNull()).count(),
        "compare: trees only in the Spark output": joined.filter(F.col("old.name").isNull()).count(),
    }
    both = joined.filter(F.col("old.name").isNotNull() & F.col("new.name").isNotNull())
    differ = both.agg(*[F.sum(F.when(~F.col(f"old.{n}").eqNullSafe(F.col(f"new.{n}")), 1).otherwise(0)).alias(n)
                        for n in TREE_FIELDS if n != "key"]).first().asDict()
    result.update({f"compare: trees with a different {n}": c for n, c in differ.items() if c})
    if not any(differ.values()):
        result["compare: trees with a different field"] = 0
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=OUT)
    parser.add_argument("--compare", help="old trees.jsonl to compare the result with")
    args = parser.parse_args()

    spark = get_spark("extract_trees")
    stats = {}

    started = time.time()
    tso_manifest = load_manifest(spark, TSO_MANIFEST, "tso").cache()
    gardenia_manifest = load_manifest(spark, GARDENIA_MANIFEST, "gardenia").cache()
    stats["tso manifest entries"] = tso_manifest.count()
    stats["gardenia manifest entries"] = gardenia_manifest.count()
    stats["manifest entries without a saved file"] = (missing_files(spark, tso_manifest, TSO_PAGES)
                                                      + missing_files(spark, gardenia_manifest, GARDENIA_PAGES))

    tso_trees = extract_tso(load_pages(spark, tso_manifest, TSO_PAGES), stats)
    gardenia_plants = gardenia_manifest.filter(F.col("kind") == "plant")
    resolved = gardenia_pages(load_pages(spark, gardenia_plants, GARDENIA_PAGES), tso_trees, stats)
    gardenia_stats(resolved, stats)
    trees = merge(tso_trees, aggregate_gardenia(resolved, tso_trees))

    trees.repartition(1).sortWithinPartitions("key").write.mode("overwrite").json(args.out)
    trees = spark.read.schema(trees.schema).json(args.out)
    tree_stats(trees, stats)
    stats["seconds"] = round(time.time() - started)
    if args.compare:
        stats.update(compare(spark, trees, args.compare))

    lines = [f"{name}\t{value}" for name, value in stats.items()]
    with open(STATS_OUT, "w", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")
    print(f"\nWrote trees to {args.out}, statistics to {STATS_OUT}")
    print("\n".join(lines))
    spark.stop()


if __name__ == "__main__":
    main()
