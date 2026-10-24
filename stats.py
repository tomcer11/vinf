"""
Statistics of the downloaded data, the extracted records, the mapping and the index

  crawl      pages per kind, size of the saved HTML (bytes and size on disk
             with 4 KiB clusters), size of the cache, requests in the crawl logs
  tokens     tiktoken token counts (cl100k_base and o200k_base) of the raw HTML
             and of the plain text the extractor got out of it
  extractor  number of records and how many have each field
  mapping    gardenia plants per mapping level (data/mapping.csv)
  index      documents, terms and postings per field (index/index.json.gz)

Output: printed as Markdown tables (ready for the wiki), and saved to
        data/stats.json and data/stats.md

Usage:
  python stats.py                    # everything (tokenizing 3.5 GB of HTML takes a few minutes)
  python stats.py --no-html-tokens   # skip the tokens of the raw HTML
"""

import argparse
import csv
import gzip
import json
import math
import time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

import tiktoken

from extractor import GARDENIA_OUT, TSO_OUT

DATA_DIR = Path("./data")
STATS_JSON = DATA_DIR / "stats.json"
STATS_MD = DATA_DIR / "stats.md"
CLUSTER = 4096
ENCODINGS = ("cl100k_base", "o200k_base")

SOURCES = {
    "tso": {
        "label": "Trees and Shrubs Online",
        "pages": Path("./pages"),
        "cache": Path("./cache"),
        "manifest": Path("./manifest.json"),
        "log": Path("./crawl_log.csv"),
        "records": TSO_OUT,
    },
    "gardenia": {
        "label": "gardenia.net",
        "pages": Path("./gardenia/pages"),
        "cache": Path("./gardenia/cache"),
        "manifest": Path("./gardenia/manifest.json"),
        "log": Path("./gardenia/crawl_log.csv"),
        "records": GARDENIA_OUT,
    },
}

# fields counted in the "fields filled" table
TSO_FIELDS = ["family", "common_names", "synonym_names", "description", "editorial_note",
              "distribution", "habitat", "habitat_from_text", "usda", "rhs", "conservation", "height",
              "altitude", "mountain", "pests", "pest_sentences", "main_text", "sections"]
GARDENIA_FIELDS = ["common_names", "scientific_synonyms", "plant_type", "usda", "height", "exposure",
                   "soil_type", "tolerances", "attracts", "garden_uses", "native_to", "habitat_sentences",
                   "pests", "pest_sentences", "description"]


def mb(n: int) -> str:
    return f"{n / 1e6:,.1f} MB"


def dir_size(path: Path) -> dict:
    files = [p for p in path.iterdir() if p.is_file()] if path.exists() else []
    sizes = [p.stat().st_size for p in files]
    return {
        "files": len(files),
        "bytes": sum(sizes),
        "on_disk_bytes": sum(math.ceil(s / CLUSTER) * CLUSTER for s in sizes),
    }


def crawl_stats(source: dict) -> dict:
    manifest = json.loads(source["manifest"].read_text(encoding="utf-8"))
    kinds = Counter(item.get("kind", "species/genus") for item in manifest)
    if "kind" not in manifest[0]:     # TSO manifest: kind from the URL depth
        kinds = Counter("species" if item["url"].rstrip("/").count("/") >= 5 else "genus"
                        for item in manifest)
        # the 26 listing pages /articles/a/ ... /articles/z/ are saved but not in the manifest
        kinds["listing a-z"] = sum(1 for p in source["pages"].glob("articles_?.html"))
    statuses = Counter()
    if source["log"].exists():
        with source["log"].open(encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                statuses[row.get("status_code", "?")] += 1
    return {
        "manifest_pages": len(manifest),
        "kinds": dict(kinds),
        "saved_pages": dir_size(source["pages"]),
        "cache": dir_size(source["cache"]),
        "requests_logged": sum(statuses.values()),
        "http_200": statuses.get("200", 0),
        "served_from_cache": statuses.get("cached", 0),
        "other_statuses": {k: v for k, v in statuses.items() if k not in ("200", "cached")},
    }


def record_text(record: dict) -> str:
    """Plain text of an extracted record (what an indexer reads)."""
    if record["source"] == "tso":
        parts = [record["title"], record["description"], record["distribution"], record["habitat"],
                 record["usda_zone"], record["rhs_rating"], record["conservation_status"],
                 record["awards"], record["taxonomic_note"], record["main_text"],
                 " ".join(record["common_names"]), " ".join(record["synonyms"])]
        parts += [s["name"] + " " + s["text"] for s in record["sections"]]
    else:
        parts = [record["title"], " ".join(record["common_names"]), record["description"]]
        parts += [" ".join(v) if isinstance(v, list) else str(v)
                  for k, v in record.items()
                  if k in ("hardiness", "plant_type", "exposure", "soil_type", "soil_ph",
                           "tolerances", "attracts", "garden_uses", "height_raw", "spread_raw")]
    return "\n".join(p for p in parts if p)


def _count_tokens(text: str) -> tuple[int, int, int]:
    return (len(text),) + tuple(len(tiktoken.get_encoding(e).encode_ordinary(text)) for e in ENCODINGS)


def _count_file(path: str) -> tuple[int, int, int]:
    return _count_tokens(Path(path).read_text(encoding="utf-8", errors="replace"))


def token_stats(source: dict, html: bool, workers: int) -> dict:
    with source["records"].open(encoding="utf-8") as f:
        texts = [record_text(json.loads(line)) for line in f]
    result = {"records": len(texts)}
    with Pool(workers) as pool:
        counts = pool.map(_count_tokens, texts, chunksize=64)
        result["text"] = {"chars": sum(c[0] for c in counts),
                          **{e: sum(c[i + 1] for c in counts) for i, e in enumerate(ENCODINGS)}}
        if html:
            files = [str(p) for p in source["pages"].iterdir() if p.is_file()]
            counts = pool.map(_count_file, files, chunksize=16)
            result["html"] = {"files": len(files), "chars": sum(c[0] for c in counts),
                              **{e: sum(c[i + 1] for c in counts) for i, e in enumerate(ENCODINGS)}}
    return result


def field_stats(path: Path, fields: list[str]) -> dict:
    filled = Counter()
    n = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            n += 1
            for name in fields:
                if record.get(name):
                    filled[name] += 1
    return {"records": n, "jsonl_bytes": path.stat().st_size, "filled": {k: filled[k] for k in fields}}


def mapping_stats() -> dict:
    path = DATA_DIR / "mapping.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    levels = Counter(r["level"] for r in rows)
    return {
        "gardenia_plants": len(rows),
        "levels": dict(levels),
        "mapped": sum(v for k, v in levels.items() if k != "none"),
        "tso_pages_with_gardenia": len({r["tso_url"].split("#")[0] for r in rows if r["tso_url"]}),
        "woody_not_in_tso": sum(1 for r in rows if r["level"] == "none" and r["woody"] == "True"),
    }


def index_stats() -> dict:
    path = Path("./index/index.json.gz")
    if not path.exists():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        meta = json.load(f)["meta"]
    meta["file_bytes"] = path.stat().st_size
    return meta


def to_markdown(stats: dict) -> str:
    out = ["## Crawl", "",
           "| | Trees and Shrubs Online | gardenia.net |", "|---|---:|---:|"]
    t, g = stats["crawl"]["tso"], stats["crawl"]["gardenia"]
    mapped = (stats.get("mapping") or {}).get("mapped", 0)
    rows = [
        ("pages in the manifest", t["manifest_pages"], g["manifest_pages"]),
        ("pages per kind", ", ".join(f"{k} {v}" for k, v in t["kinds"].items()),
         ", ".join(f"{k} {v}" for k, v in g["kinds"].items())),
        ("HTML files saved", t["saved_pages"]["files"], g["saved_pages"]["files"]),
        ("relevant for the project",
         f"{t['manifest_pages']} (genus + species pages; the a-z listings are navigation)",
         f"{mapped} plant pages mapped to TSO (trees and shrubs)"),
        ("size of the HTML", mb(t["saved_pages"]["bytes"]), mb(g["saved_pages"]["bytes"])),
        ("size on disk (4 KiB clusters)", mb(t["saved_pages"]["on_disk_bytes"]), mb(g["saved_pages"]["on_disk_bytes"])),
        ("average page", f"{t['saved_pages']['bytes'] / max(1, t['saved_pages']['files']) / 1e3:.0f} kB",
         f"{g['saved_pages']['bytes'] / max(1, g['saved_pages']['files']) / 1e3:.0f} kB"),
        ("cache (files / size)", f"{t['cache']['files']} / {mb(t['cache']['bytes'])}",
         f"{g['cache']['files']} / {mb(g['cache']['bytes'])}"),
        ("requests in the crawl log (all runs)", t["requests_logged"], g["requests_logged"]),
        ("of them HTTP 200 / served from cache", f"{t['http_200']} / {t['served_from_cache']}",
         f"{g['http_200']} / {g['served_from_cache']}"),
    ]
    out += [f"| {a} | {b} | {c} |" for a, b, c in rows]

    out += ["", "## Tokens (tiktoken)", "",
            "| | | characters | cl100k_base | o200k_base |", "|---|---|---:|---:|---:|"]
    for key, label in (("tso", "Trees and Shrubs Online"), ("gardenia", "gardenia.net")):
        tok = stats["tokens"][key]
        for part, name in (("html", "raw HTML"), ("text", "extracted text")):
            if part in tok:
                out.append(f"| {label} | {name} | {tok[part]['chars']:,} | "
                           f"{tok[part]['cl100k_base']:,} | {tok[part]['o200k_base']:,} |")

    out += ["", "## Extractor", ""]
    for key in ("tso", "gardenia"):
        ex = stats["extractor"][key]
        out += [f"**{SOURCES[key]['label']}**: {ex['records']} records, {mb(ex['jsonl_bytes'])} JSONL", "",
                "| field | records | % |", "|---|---:|---:|"]
        out += [f"| {k} | {v} | {100 * v / ex['records']:.1f} |" for k, v in ex["filled"].items()]
        out.append("")

    m = stats.get("mapping")
    if m:
        out += ["## gardenia -> TSO mapping", "", "| level | plants |", "|---|---:|"]
        out += [f"| {k} | {m['levels'].get(k, 0)} |" for k in ("cultivar", "species", "synonym", "genus", "none")]
        out += [f"| **mapped** | **{m['mapped']}** ({100 * m['mapped'] / m['gardenia_plants']:.1f} %) |",
                "", f"TSO pages with at least one gardenia plant: {m['tso_pages_with_gardenia']}; "
                    f"woody gardenia plants without a TSO genus: {m['woody_not_in_tso']}", ""]

    ix = stats.get("index")
    if ix:
        out += ["## Index", "", f"{ix['documents']} documents, {ix['tokens']:,} tokens "
                f"(own tokenizer), {mb(ix['file_bytes'])} index file", "",
                "| field | terms | postings |", "|---|---:|---:|"]
        out += [f"| {f} | {ix['vocabulary'][f]:,} | {ix['postings'][f]:,} |" for f in ix["vocabulary"]]
    return "\n".join(out) + "\n"


def main(html_tokens: bool, workers: int):
    started = time.time()
    stats = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "crawl": {}, "tokens": {}, "extractor": {}}
    for key, source in SOURCES.items():
        print(f"{key}: crawl ...", flush=True)
        stats["crawl"][key] = crawl_stats(source)
        print(f"{key}: tokens ...", flush=True)
        stats["tokens"][key] = token_stats(source, html_tokens, workers)
    stats["extractor"]["tso"] = field_stats(TSO_OUT, TSO_FIELDS)
    stats["extractor"]["gardenia"] = field_stats(GARDENIA_OUT, GARDENIA_FIELDS)
    stats["mapping"] = mapping_stats()
    stats["index"] = index_stats()

    DATA_DIR.mkdir(exist_ok=True)
    STATS_JSON.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown = to_markdown(stats)
    STATS_MD.write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"-> {STATS_JSON}, {STATS_MD} ({time.time() - started:.0f} s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Statistics of the crawled data and the index")
    parser.add_argument("--no-html-tokens", action="store_true", help="skip tokenizing the raw HTML")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    main(not args.no_html_tokens, args.workers)
