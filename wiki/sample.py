"""
A small piece of the Wikipedia dump for trying the Spark job, and a plain
Python count of its pages to check what Spark reads.

The dump is "multistream": a concatenation of independent bzip2 streams of
100 pages each. Cutting the file just before a stream header gives a smaller
file that is still a valid multistream .bz2 (it only lacks </mediawiki>).

Usage (from the repo root):
  python -m wiki.sample cut   --dump C:/vinf-data/enwiki-...xml.bz2 --mb 400 --out C:/vinf-data/sample.xml.bz2
  python -m wiki.sample count --dump C:/vinf-data/sample.xml.bz2
"""

import argparse
import bz2
import re
from collections import Counter

# "BZh9" (stream header, block size 900k) followed by the block magic 0x314159265359
STREAM_HEADER = b"BZh91AY&SY"
CHUNK = 1 << 20

TITLE_RE = re.compile(r"<title>(.*?)</title>")
NS_RE = re.compile(r"<ns>(\d+)</ns>")
REDIRECT_RE = re.compile(r'<redirect title="')
# the same pattern as spark_jobs.extract_wiki.TAXOBOX
TAXOBOX_RE = re.compile(
    r"\{\{\s*(?i:speciesbox|taxobox|automatic[ _]taxobox|subspeciesbox|infraspeciesbox|hybridbox)\s*[|}\n]")


def cut(dump: str, megabytes: int, out: str):
    """Copy the first `megabytes` MB of the dump, ending before a stream header."""
    with open(dump, "rb") as src:
        head = src.read(megabytes * CHUNK)
        tail = src.read(CHUNK)
    end = (head + tail).find(STREAM_HEADER, len(head))
    if end < 0:
        raise SystemExit("no stream header found after the cut, try another size")
    with open(out, "wb") as dst:
        dst.write((head + tail)[:end])
    print(f"wrote {end / CHUNK:.1f} MB to {out}")


def count(dump: str):
    """Pages of a (sample) dump counted page by page in plain Python."""
    stats = Counter()
    page = []
    opener = bz2.open if dump.endswith(".bz2") else open
    with opener(dump, "rt", encoding="utf-8") as src:
        for line in src:
            if "<page>" in line:
                page = []
            page.append(line)
            if "</page>" in line:
                text = "".join(page)
                ns = NS_RE.search(text).group(1)
                stats["pages"] += 1
                if ns == "0":
                    stats["main namespace pages"] += 1
                    if REDIRECT_RE.search(text):
                        stats["main namespace redirects"] += 1
                    elif TAXOBOX_RE.search(text):
                        stats["taxon articles"] += 1
    for name, value in stats.items():
        print(f"{name}\t{value}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["cut", "count"])
    parser.add_argument("--dump", required=True)
    parser.add_argument("--mb", type=int, default=400)
    parser.add_argument("--out")
    args = parser.parse_args()
    if args.action == "cut":
        cut(args.dump, args.mb, args.out)
    else:
        count(args.dump)


if __name__ == "__main__":
    main()
