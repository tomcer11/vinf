"""
Spark job: Trees (TSO + gardenia) JOIN Wikipedia taxon articles.

Why the latin name: both sources identify a taxon by its scientific name.
English names are ambiguous ("red cedar" is Juniperus virginiana, Thuja
plicata, Toona ciliata ...), a binomial names one species. Both sides are
normalized by the same function (wiki.wikitext.join_key, built on the
extractor's name_key), so 'Platanus x hispanica' meets 'Platanus ×hispanica'.

Every tree looks up its name and its synonyms; the wiki side offers four kinds
of keys. A tree takes the best article by this priority:

  tree      wiki                                                   example
  name    = taxobox latin name   (genus + species / taxon)         Kalmia latifolia
  name    = article title                                          Abies alba
  name    = title of a redirect to a species-level taxon article   Malus domestica -> Apple
  name    = synonym listed in the article's taxobox                Sorbus aria -> Aria edulis
  synonym = the same four, only when the name found nothing

Only keys of two or more words (species level) take part, so a tree never
gets the article of its genus. Synonyms shared by two trees or equal to the
name of another tree are left out (the same rule as in the extractor).

A match that goes through a synonym (a synonym of the tree, or one listed in
the article) must end in an article whose genus is the genus of the tree or
of one of its synonyms. Synonym lists hold homonyms of other kingdoms
(Thymelaea tinctoria, syn. Passerina nivalis -> redirect -> Snow bunting,
Plectrophenax nivalis) and misapplied names (Skimmia reevesiana is listed
under Ilex cornuta). A redirect of the tree's own name needs no such check:
genera move (Callistemon linearis -> Melaleuca linearis, Sorbus aria -> Aria
edulis) and all 27 such redirects to a genus unknown to our data were right.

The tree side is small (~6.7k trees), so it is broadcast to the wiki side
(~0.5 M taxon articles, ~11 M redirects): no shuffle of the wiki data.
The Python UDFs run only on taxon articles (keys) and on the joined articles
(all attributes); redirects are filtered in the JVM first.

Output:
  output/spark/trees_wiki/       the trees with wiki_* fields (JSON Lines, sorted by key)
  output/spark/join_pairs.tsv    tree key, how it was joined, wiki title
  output/spark/join_stats.tsv    the numbers for the documentation

Usage (in the container, from /work):
  python -m spark_jobs.join_wiki
  python -m spark_jobs.join_wiki --wiki /data/wiki_sample --trees output/data/trees.jsonl   # quick try
"""

import argparse
import time

from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType, StringType, StructField, StructType
from pyspark.sql.window import Window

from extractor.tree import species_key
from spark_jobs.extract_wiki import read_saved, wiki_pages
from spark_jobs.session import get_spark
from wiki.wikitext import article_keys, join_key, parse_article, title_key

TREES = "output/spark/trees"
WIKI = "/data/wiki"
OUT = "output/spark/trees_wiki"
PAIRS_OUT = "output/spark/join_pairs.tsv"
STATS_OUT = "output/spark/join_stats.tsv"
WIKI_URL = "https://en.wikipedia.org/wiki/"

STRINGS = ArrayType(StringType())
KEYS_SCHEMA = StructType([
    StructField("latin_key", StringType()),
    StructField("title_key", StringType()),
    StructField("synonym_keys", STRINGS),
])
# wiki_* fields added to a Tree, in this order
ARTICLE_FIELDS = [
    ("latin", StringType()), ("authority", StringType()), ("status", StringType()),
    ("common_names", STRINGS), ("synonyms", STRINGS), ("lead", StringType()),
    ("description", StringType()), ("distribution", StringType()), ("ecology", StringType()),
    ("uses", StringType()), ("categories", STRINGS),
]
ARTICLE_SCHEMA = StructType([StructField(name, kind) for name, kind in ARTICLE_FIELDS])

# priority of the wiki keys (lower is better); a match by a tree synonym adds 10
WIKI_KEY_RANK = {"taxobox": 0, "title": 1, "redirect": 2, "wiki synonym": 3}

article_keys_udf = F.udf(article_keys, KEYS_SCHEMA)
parse_article_udf = F.udf(parse_article, ARTICLE_SCHEMA)
join_key_udf = F.udf(join_key, StringType())
title_key_udf = F.udf(title_key, StringType())
species_join_key_udf = F.udf(lambda name: join_key(species_key(name)[0]), StringType())


def species_level(column):
    """Keys of at least two words: 'fagus sylvatica', not the genus 'fagus'."""
    return F.size(F.split(column, " ")) >= 2


# === the two sides of the join ===================================================

def wiki_lookup(taxa, redirects):
    """(lookup, title, how): every key under which a taxon article can be found."""
    taxobox = taxa.select(F.col("latin_key").alias("lookup"), "title", F.lit("taxobox").alias("how"))
    title = taxa.select(F.col("title_key").alias("lookup"), "title", F.lit("title").alias("how"))

    # redirects to a taxon article (exact title, in the JVM) whose latin name is a species,
    # then the Python key only for these; "Acer amplum -> Acer#Species" would give the genus
    species_titles = taxa.filter(species_level("latin_key")).select(F.col("title").alias("target"))
    redirect = (redirects
                .withColumn("target", F.regexp_replace("target", "#.*$", ""))
                .join(species_titles, "target", "left_semi")
                .select(title_key_udf("title").alias("lookup"), F.col("target").alias("title"),
                        F.lit("redirect").alias("how")))

    # a synonym listed in two articles points nowhere
    synonym = taxa.select(F.explode("synonym_keys").alias("lookup"), "title").distinct()
    unique = synonym.groupBy("lookup").count().filter("count = 1").select("lookup")
    synonym = synonym.join(unique, "lookup", "left_semi").withColumn("how", F.lit("wiki synonym"))

    lookup = taxobox.unionByName(title).unionByName(redirect).unionByName(synonym)
    return lookup.filter(species_level("lookup")).distinct()


def genus_of(name):
    """'× Pyraria irregularis' -> 'pyraria' (lower case, no hybrid sign)."""
    return F.lower(F.regexp_extract(name, r"^[×+ ]*([^ ]+)", 1))


def tree_lookup(trees):
    """(tree_key, lookup, via, genera): the tree's own name and its unambiguous
    synonyms; genera = the genus of the name and of every synonym."""
    genera = F.array_distinct(F.transform(F.concat(F.array("name"), "synonyms"), genus_of))
    trees = trees.withColumn("genera", genera)
    names = trees.select(F.col("key").alias("tree_key"), join_key_udf("key").alias("lookup"),
                         F.lit("name").alias("via"), "genera")
    synonyms = (trees.select(F.col("key").alias("tree_key"), "genera", F.explode("synonyms").alias("synonym"))
                .select("tree_key", "genera", species_join_key_udf("synonym").alias("lookup"))
                .distinct())
    shared = synonyms.groupBy("lookup").count().filter("count > 1").select("lookup")
    synonyms = (synonyms.join(shared, "lookup", "left_anti")
                .join(names.select("lookup"), "lookup", "left_anti")       # the name of another tree
                .withColumn("via", F.lit("synonym")))
    return names.unionByName(synonyms).filter(species_level("lookup"))


def best_matches(tree_keys, wiki_keys, taxa):
    """One article per tree: the best (via, how); ties -> the article whose
    title is the key itself, then the alphabetically first title. A match
    through a synonym needs the article's genus among the tree's genera."""
    rank = F.create_map(*[x for how, r in WIKI_KEY_RANK.items() for x in (F.lit(how), F.lit(r))])
    candidates = wiki_keys.join(F.broadcast(tree_keys), "lookup")
    article_genus = taxa.select("title", genus_of("latin_key").alias("article_genus"))
    candidates = article_genus.join(F.broadcast(candidates), "title")
    through_synonym = (F.col("via") == "synonym") | (F.col("how") == "wiki synonym")
    candidates = (candidates
                  .filter(~through_synonym | F.array_contains("genera", F.col("article_genus")))
                  .withColumn("rank", rank[F.col("how")] + F.when(F.col("via") == "synonym", 10).otherwise(0))
                  .withColumn("not_exact", title_key_udf("title") != F.col("lookup")))
    order = Window.partitionBy("tree_key").orderBy("rank", "not_exact", "title")
    return (candidates.withColumn("n", F.row_number().over(order))
            .filter("n = 1")
            .select("tree_key", "title", F.concat_ws(" = ", "via", "how").alias("join_path")))


# === statistics ======================================================================

def join_stats(trees, matches, taxa_count: int, redirect_count: int) -> list[tuple[str, object]]:
    joined = trees.join(matches, trees["key"] == matches["tree_key"], "left")
    sources = F.array_join("sources", " + ")
    stats = [
        ("wiki taxon articles", taxa_count),
        ("wiki redirects (main namespace)", redirect_count),
        ("trees", trees.count()),
        ("trees joined to a wiki article", matches.count()),
        ("UNIQUE wiki articles joined", matches.select("title").distinct().count()),
    ]
    shared = matches.groupBy("title").count().filter("count > 1")
    stats.append(("wiki articles joined to 2+ trees", shared.count()))
    stats.append(("trees sharing an article with another tree", shared.agg(F.sum("count")).first()[0] or 0))
    for path, count in matches.groupBy("join_path").count().orderBy(F.desc("count")).collect():
        stats.append((f"joined by: tree {path}", count))
    for source, total, hit in (joined.groupBy(sources.alias("s"))
                               .agg(F.count(F.lit(1)), F.count("title"))
                               .orderBy("s").collect()):
        stats.append((f"joined from {source}", f"{hit} of {total} ({100 * hit / total:.1f} %)"))
    return stats


# === main =================================================================================

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trees", default=TREES)
    parser.add_argument("--wiki", default=WIKI)
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args()

    started = time.time()
    spark = get_spark("join_wiki")
    trees = spark.read.json(args.trees).cache()

    # the texts (GBs) are neither cached nor shuffled: the duplicates of the dump
    # pass (see extract_wiki) are dropped after the projection to the small keys
    taxa_text = read_saved(spark, args.wiki, "taxon")
    taxa = (taxa_text.select("id", "title", article_keys_udf("title", "text").alias("k"))
            .dropDuplicates(["id"])
            .select("title", "k.*")
            .cache())
    redirects = wiki_pages(spark, args.wiki, "redirect").select("title", "target").cache()
    taxa_count, redirect_count = taxa.count(), redirects.count()

    matches = best_matches(tree_lookup(trees), wiki_lookup(taxa, redirects), taxa).cache()

    # all attributes, parsed only for the joined articles
    articles = (taxa_text.join(matches.select("title").distinct(), "title", "left_semi")
                .dropDuplicates(["id"])
                .select("title", parse_article_udf("title", "text").alias("a"))
                .select("title", "a.*"))
    wiki_columns = [F.col("title").alias("wiki_title"),
                    F.concat(F.lit(WIKI_URL), F.regexp_replace("title", " ", "_")).alias("wiki_url"),
                    F.col("join_path").alias("wiki_join")]
    wiki_columns += [F.col(name).alias(f"wiki_{name}") for name, _ in ARTICLE_FIELDS]
    wiki = matches.join(articles, "title").select(F.col("tree_key").alias("key"), *wiki_columns)

    out = trees.join(wiki, "key", "left")
    for name, kind in [("title", None), ("url", None), ("join", None)] + ARTICLE_FIELDS:
        empty = F.array().cast(STRINGS) if kind == STRINGS else F.lit("")
        out = out.withColumn(f"wiki_{name}", F.coalesce(F.col(f"wiki_{name}"), empty))
    out = out.select(*trees.columns, *[c for c in out.columns if c.startswith("wiki_")])
    out.repartition(1).sortWithinPartitions("key").write.mode("overwrite").json(args.out)
    result = spark.read.json(args.out).filter(F.col("wiki_title") != "").cache()

    with open(PAIRS_OUT, "w", encoding="utf-8") as tsv:
        tsv.write("tree_key\tsources\tjoin_path\twiki_title\twiki_latin\n")
        for row in result.select("key", "sources", "wiki_join", "wiki_title", "wiki_latin").orderBy("key").collect():
            tsv.write(f"{row.key}\t{'+'.join(row.sources)}\t{row.wiki_join}\t{row.wiki_title}\t{row.wiki_latin}\n")

    stats = join_stats(trees, matches, taxa_count, redirect_count)
    # how many joined trees got each attribute (non-empty)
    filled = result.agg(*[F.sum(F.when(F.length(F.col(f"wiki_{name}")) > 0 if kind != STRINGS
                                       else F.size(f"wiki_{name}") > 0, 1).otherwise(0)).alias(name)
                          for name, kind in ARTICLE_FIELDS]).first().asDict()
    stats += [(f"joined trees with wiki_{name}", count) for name, count in filled.items()]
    stats.append(("seconds", round(time.time() - started)))
    with open(STATS_OUT, "w", encoding="utf-8") as tsv:
        tsv.write("".join(f"{name}\t{value}\n" for name, value in stats))
    print(f"\nWrote {args.out}, {PAIRS_OUT}, {STATS_OUT}")
    print("".join(f"{name:55} {value}\n" for name, value in stats))
    spark.stop()


if __name__ == "__main__":
    main()
