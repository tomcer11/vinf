"""
Spark job: one pass over the English Wikipedia dump -> taxon articles and redirects.

The dump (enwiki-20261001-pages-articles-multistream.xml.bz2, 27 GB) is read
as it is: bzip2 is a splittable codec, so Spark decompresses its parts in
parallel and the ~110 GB of XML never lands on the disk. One record is one
<page>: the records are separated by "</page>" instead of a newline.

Everything that touches the whole dump runs in the JVM (regexp_extract, rlike).
The Python regexes of wiki/wikitext.py run later, in join_wiki, on the saved
taxon articles only, because sending 110 GB of text to Python workers would
be many times slower.

Hadoop's reader of bzip2 splits with a custom record separator sometimes
returns the page at a split boundary twice (2 pages of 42 352 in a 400 MB
sample, none lost). The pass over the dump stays map-only (no shuffle of
110 GB); the duplicates are dropped by page id when the small output is read
(wiki_pages).

Output, gzip JSON Lines, one directory per kind (partitionBy):
  <out>/pages/kind=taxon     articles with a taxobox: id, title, text (raw wikitext, XML escaped)
  <out>/pages/kind=redirect  redirects of the main namespace: id, title, target
  <out>/pages/kind=other     all other pages, only id and ns (for the statistics)
  <out>/dump_stats.tsv       counts over the whole dump

Usage (in the container, from /work):
  python -m spark_jobs.extract_wiki --dump /data/sample.xml.bz2 --out /data/wiki_sample
  python -m spark_jobs.extract_wiki          # the whole dump -> /data/wiki
"""

import argparse
import time

from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, StringType, StructField, StructType

from spark_jobs.session import get_spark

DUMP = "/data/enwiki-20261001-pages-articles-multistream.xml.bz2"
OUT = "/data/wiki"

# A taxobox template at the start of a template call: {{Speciesbox | ...,
# {{Automatic taxobox\n ... (Java regex, matched in the JVM)
TAXOBOX = (r"\{\{\s*(?i:speciesbox|taxobox|automatic[ _]taxobox|subspeciesbox"
           r"|infraspeciesbox|hybridbox)\s*[|}\n]")


def xml_unescape(column):
    """The five XML entities of the dump (&amp; last, so '&amp;lt;' stays '&lt;')."""
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#039;", "'"), ("&amp;", "&")):
        column = F.regexp_replace(column, entity, char)
    return column


def read_pages(spark, dump: str):
    """One row per <page>: id, title, ns, redirect target, the raw page XML."""
    raw = spark.read.text(dump, lineSep="</page>")
    pages = raw.select(
        F.regexp_extract("value", r"<ns>(\d+)</ns>\s*<id>(\d+)</id>", 2).alias("id"),
        xml_unescape(F.regexp_extract("value", r"<title>(.*?)</title>", 1)).alias("title"),
        F.regexp_extract("value", r"<ns>(\d+)</ns>", 1).cast("int").alias("ns"),
        xml_unescape(F.regexp_extract("value", r'<redirect title="([^"]*)"', 1)).alias("target"),
        F.col("value"),
    )
    # the text after the last </page> (</mediawiki>) is not a page
    return pages.filter(F.col("title") != "")


def classify(pages):
    """kind: 'redirect' and 'taxon' (main namespace only), 'other' for the rest."""
    main = F.col("ns") == 0
    return pages.withColumn(
        "kind",
        F.when(main & (F.col("target") != ""), "redirect")
         .when(main & F.col("value").rlike(TAXOBOX), "taxon")
         .otherwise("other"),
    )


def project(pages):
    """The columns saved for each kind (NULL columns are not written to JSON)."""
    kind = F.col("kind")
    return pages.select(
        "kind", "id", "ns",
        F.when(kind != "other", F.col("title")).alias("title"),
        F.when(kind == "redirect", F.col("target")).alias("target"),
        F.when(kind == "taxon", F.regexp_extract("value", r"(?s)<text[^>]*>(.*)</text>", 1)).alias("text"),
    )


# the schema of the output; given when reading, so Spark does not scan GBs of text to infer it
PAGE_SCHEMA = StructType([StructField(name, IntegerType() if name == "ns" else StringType())
                          for name in ("id", "ns", "title", "target", "text")])


def read_saved(spark, out: str, kind: str):
    """Saved pages of one kind as written (a page at a split boundary may be there twice)."""
    return spark.read.schema(PAGE_SCHEMA).json(f"{out}/pages/kind={kind}")


def wiki_pages(spark, out: str, kind: str):
    """Saved pages of one kind, each page once (see the split boundary note above).
    For the taxon texts, drop the duplicates after a projection instead (join_wiki)."""
    return read_saved(spark, out, kind).dropDuplicates(["id"])


def dump_stats(spark, out: str) -> dict:
    """Counts over the whole dump, from the saved output."""
    pages = spark.read.schema(PAGE_SCHEMA).json(f"{out}/pages").select("id", "ns", "kind")
    records = pages.count()
    row = pages.dropDuplicates(["id"]).agg(
        F.count(F.lit(1)).alias("pages"),
        F.sum(F.when(F.col("ns") == 0, 1).otherwise(0)).alias("main namespace pages"),
        F.sum(F.when(F.col("kind") == "redirect", 1).otherwise(0)).alias("main namespace redirects"),
        F.sum(F.when(F.col("kind") == "taxon", 1).otherwise(0)).alias("taxon articles"),
    ).first().asDict()
    row["articles (main namespace, no redirect)"] = row["main namespace pages"] - row["main namespace redirects"]
    row["duplicate records at split boundaries"] = records - row["pages"]
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dump", default=DUMP)
    parser.add_argument("--out", default=OUT)
    parser.add_argument("--split-mb", type=int, default=128, help="max size of one input split (one task)")
    args = parser.parse_args()

    spark = get_spark("extract_wiki")
    spark.conf.set("spark.sql.files.maxPartitionBytes", f"{args.split_mb}m")

    pages = project(classify(read_pages(spark, args.dump)))
    print(f"input splits (tasks): {pages.rdd.getNumPartitions()}", flush=True)

    started = time.time()
    (pages.write.mode("overwrite")
          .partitionBy("kind")
          .option("compression", "gzip")
          .json(f"{args.out}/pages"))
    stats = dump_stats(spark, args.out)
    stats["seconds"] = round(time.time() - started)

    lines = [f"{name}\t{value}" for name, value in stats.items()]
    with open(f"{args.out}/dump_stats.tsv", "w", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    spark.stop()


if __name__ == "__main__":
    main()
