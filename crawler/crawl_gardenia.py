"""
Crawler for gardenia.net (plants database)

Crawl plan, strict depth with a queue and a cache:
  1. https://www.gardenia.net/plants/genera          (index of all genera)
       -> take every genus link   /plants/genera/<slug>
  2. each genus page, e.g. /plants/genera/abelia
       -> take every plant link   /plant/<slug>
       -> (DISCOVER_SUBGENERA) also genus links, because the sidebar of a genus
          page lists sub-genera that the index page does not (Iris ensata, Rosa
          - Climbing Rose, Apricots, Tomatoes ...)
  3. each plant page, e.g. /plant/abelia-edward-goucher
       -> saved only. Its links ("similar plants") are never read, because
          those plants are already reached through their genus page.

Every URL enters the queue at most once and every page is cached on disk, so
nothing is downloaded twice, and a stopped crawl can be restarted.

Output (separate from the trees and shrubs data):
  crawled_pages/gardenia/pages/          downloaded HTML, readable file names
  crawled_pages/gardenia/cache/          cache keyed by URL hash
  crawled_pages/gardenia/manifest.json   url, kind, file, size
  crawled_pages/gardenia/crawl_log.csv   every request

Sitemap mode (complete list of plants, recommended):
  The genus pages only show part of the plants (the rest is loaded by JavaScript
  from /refine_by, which robots.txt disallows). The sitemap named in robots.txt
  lists every plant page:
    sitemap_index.xml -> plant-sitemap.xml, plant-sitemap2.xml ... (/plant/<slug>)
  Plants already in the cache (from the genus-page crawl) are not downloaded again,
  only the missing ones are. The manifest of the earlier crawl is kept and extended.

Usage:
  python -m crawler.crawl_gardenia --probe                          # 1 request: robots.txt + genus page check
  python -m crawler.crawl_gardenia --from-sitemap --dry-run         # read sitemaps, count missing plants (12 requests)
  python -m crawler.crawl_gardenia --from-sitemap --max-plants 50   # download only 50 missing plants (trial)
  python -m crawler.crawl_gardenia --from-sitemap                   # download all missing plants (safe to stop and restart)
  python -m crawler.crawl_gardenia --from-sitemap --refresh-sitemap # ignore the cached sitemap files, read them again
  python -m crawler.crawl_gardenia --dry-run                        # old mode: index + genus pages, count plant URLs
  python -m crawler.crawl_gardenia                                  # old mode: full genus-page crawl
"""

import argparse
import hashlib
import html as htmllib
import json
import re
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse

from crawler.crawler_config import PoliteSession, logger, USER_AGENT

DOMAIN = "www.gardenia.net"
SEED_URL = f"https://{DOMAIN}/plants/genera"
GENUS_EXAMPLE = f"https://{DOMAIN}/plants/genera/abelia"
PLANT_EXAMPLE = f"https://{DOMAIN}/plant/abelia-edward-goucher"

OUT_DIR = Path("./crawled_pages/gardenia")
PAGES_DIR = OUT_DIR / "pages"
CACHE_DIR = OUT_DIR / "cache"
LOG_FILE = OUT_DIR / "crawl_log.csv"
MANIFEST_PATH = OUT_DIR / "manifest.json"
MANIFEST_FLUSH_EVERY = 500

# Also take genus links from genus pages (finds the sub-genera). Set to False to
# crawl only the genera listed on /plants/genera.
DISCOVER_SUBGENERA = True

GENUS_PATH_RE = re.compile(r"^/plants/genera/[^/]+$")
PLANT_PATH_RE = re.compile(r"^/plant/[^/]+$")

# href of every <a ...> tag: double quoted, single quoted or unquoted value
ANCHOR_HREF_RE = re.compile(
    r"""<a\b[^>]*?(?<![\w-])href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""",
    re.IGNORECASE | re.DOTALL,
)


def normalize(href: str, page_url: str) -> str | None:
    """Absolute https URL without query, fragment and trailing slash, or None
    if the link leaves the site. One page therefore has exactly one URL."""
    url = urljoin(page_url, htmllib.unescape(href.strip()))
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != DOMAIN:
        return None
    return f"https://{DOMAIN}{parsed.path.rstrip('/') or '/'}"


def extract_links(html: str, page_url: str, path_re: re.Pattern) -> list[str]:
    """Links on a page whose path matches path_re, without duplicates."""
    own = normalize(page_url, page_url)
    links, seen = [], set()
    for match in ANCHOR_HREF_RE.finditer(html):
        raw = match.group(1) or match.group(2) or match.group(3)
        if not raw:
            continue
        url = normalize(raw, page_url)
        if url is None or url == own or url in seen:
            continue
        if path_re.match(urlparse(url).path):
            seen.add(url)
            links.append(url)
    return links


def safe_filename(url: str) -> str:
    name = urlparse(url).path.strip("/").replace("/", "_") or "index"
    if len(name) > 180:
        name = name[:150] + "_" + hashlib.sha1(url.encode()).hexdigest()[:10]
    return name + ".html"


def new_session() -> PoliteSession:
    return PoliteSession(allowed_domain=DOMAIN, cache_dir=CACHE_DIR, log_file=LOG_FILE)


def probe():
    """One request: shows the robots.txt verdict and whether a genus page
    contains plant links in its HTML at all."""
    session = new_session()
    print(f"\n=== robots.txt of {DOMAIN} ===")
    if session.robots_status is None:
        print(f"Could not be fetched: {session.robots_error}")
        print("-> the crawler assumes everything is disallowed (RFC 9309).")
    else:
        print(f"HTTP status: {session.robots_status}")
        if session.robots_text:
            lines = session.robots_text.splitlines()
            print("\n".join(lines[:80]))
            if len(lines) > 80:
                print(f"... ({len(lines) - 80} more lines)")
    print(f"Parser state: allow_all={session.robots.allow_all}, "
          f"disallow_all={session.robots.disallow_all}")
    print(f"\nDelay between requests: {session.base_delay} s (+ up to {session.jitter} s jitter)")
    for label, url in (("index page", SEED_URL), ("genus page", GENUS_EXAMPLE),
                       ("plant page", PLANT_EXAMPLE)):
        print(f"robots.txt allows {label}: {session.robots.can_fetch(USER_AGENT, url)}")

    html = session.get(GENUS_EXAMPLE)
    if html is None:
        print("Could not download the genus page.")
        return
    plants = extract_links(html, GENUS_EXAMPLE, PLANT_PATH_RE)
    genera = extract_links(html, GENUS_EXAMPLE, GENUS_PATH_RE)
    print(f"\n{GENUS_EXAMPLE}")
    print(f"  genus links : {len(genera)}")
    print(f"  plant links : {len(plants)}")
    for link in plants[:10]:
        print(f"    {link}")
    if not plants:
        print("\nNo plant links in the HTML. The list of plants is probably loaded by "
              "JavaScript. Open the genus page in the browser, DevTools > Network > "
              "Fetch/XHR, reload, and look for the request that returns the plants.")


def crawl(stage1_only: bool = False, max_plants: int | None = None):
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    session = new_session()

    queue = deque([(SEED_URL, "index")])
    queued = {SEED_URL}           # every URL that ever entered the queue
    plant_urls = set()            # plants discovered on genus pages
    manifest, failed = [], []
    plants_enqueued = 0

    def enqueue(url: str, kind: str):
        nonlocal plants_enqueued
        if url in queued:
            return
        if kind == "plant":
            if stage1_only:
                return
            if max_plants is not None and plants_enqueued >= max_plants:
                return
            plants_enqueued += 1
        queued.add(url)
        queue.append((url, kind))

    try:
        while queue:
            url, kind = queue.popleft()
            logger.info("Fetching [%s]: %s (%d left in queue)", kind, url, len(queue))
            html = session.get(url)   # served from cache if already downloaded
            if html is None:
                failed.append(url)
                continue

            out_path = PAGES_DIR / safe_filename(url)
            out_path.write_text(html, encoding="utf-8")
            manifest.append({"url": url, "kind": kind, "saved_as": str(out_path),
                             "size_bytes": len(html.encode("utf-8"))})
            if len(manifest) % MANIFEST_FLUSH_EVERY == 0:
                MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))

            if kind == "index":
                for link in extract_links(html, url, GENUS_PATH_RE):
                    enqueue(link, "genus")
            elif kind == "genus":
                for link in extract_links(html, url, PLANT_PATH_RE):
                    plant_urls.add(link)
                    enqueue(link, "plant")
                if DISCOVER_SUBGENERA:
                    for link in extract_links(html, url, GENUS_PATH_RE):
                        enqueue(link, "genus")
            # kind == "plant": saved only, its links are never read
    except RuntimeError as e:
        logger.error("%s", e)

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    (OUT_DIR / "failed.txt").write_text("\n".join(failed))

    by_kind = {}
    for item in manifest:
        by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1
    print("\n--- Summary ---")
    print(f"  Pages saved           : {len(manifest)}  {by_kind}")
    print(f"  Failed / disallowed   : {len(failed)}  (see {OUT_DIR / 'failed.txt'})")
    print(f"  Unique plant URLs     : {len(plant_urls)}")
    if stage1_only:
        cached = sum(1 for u in plant_urls if session.is_cached(u))
        todo = len(plant_urls) - cached
        hours = todo * (session.base_delay + session.jitter / 2) / 3600
        print(f"  Plants already cached : {cached}")
        print(f"  Plants to download    : {todo}  (about {hours:.1f} hours)")
    print(f"  Manifest              : {MANIFEST_PATH}")


SITEMAP_INDEX_URL = f"https://{DOMAIN}/sitemap_index.xml"
PLANT_SITEMAP_PATH_RE = re.compile(r"^/plant-sitemap\d*\.xml$")
# <loc>...</loc>; the <image:loc> entries of the sitemap are not matched
LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.IGNORECASE)


def sitemap_locs(xml: str, base_url: str) -> list[str]:
    """Normalised URLs of the <loc> entries of a sitemap, without duplicates."""
    urls, seen = [], set()
    for raw in LOC_RE.findall(xml):
        url = normalize(raw, base_url)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def fetch_sitemap(session: PoliteSession, url: str, refresh: bool) -> str | None:
    """Sitemap files are cached like pages; refresh=True downloads them again."""
    if refresh:
        session._cache_path(url).unlink(missing_ok=True)
    return session.get(url)


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {}
    try:
        return {item["url"]: item for item in json.loads(MANIFEST_PATH.read_text())}
    except (ValueError, KeyError, TypeError):
        logger.warning("Could not read %s, starting a new manifest", MANIFEST_PATH)
        return {}


def crawl_from_sitemap(count_only: bool = False, max_plants: int | None = None,
                       refresh: bool = False):
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    session = new_session()

    # 1. sitemap index -> the plant sitemap files
    index = fetch_sitemap(session, SITEMAP_INDEX_URL, refresh)
    if index is None:
        print(f"Could not read {SITEMAP_INDEX_URL} (see the warning above: robots.txt or a failed request).")
        return
    files = [u for u in sitemap_locs(index, SITEMAP_INDEX_URL)
             if PLANT_SITEMAP_PATH_RE.match(urlparse(u).path)]
    if not files:
        print("The sitemap index contains no plant-sitemap*.xml files.")
        return

    # 2. plant sitemap files -> every /plant/<slug> URL
    plants = {}   # url -> sitemap file (insertion ordered, no duplicates)
    for file_url in files:
        xml = fetch_sitemap(session, file_url, refresh)
        if xml is None:
            print(f"  {file_url}: could not be read, skipped")
            continue
        found = 0
        for url in sitemap_locs(xml, file_url):
            if PLANT_PATH_RE.match(urlparse(url).path) and url not in plants:
                plants[url] = file_url
                found += 1
        print(f"  {file_url}: {found} plant URLs")

    manifest = load_manifest()
    old_plants = {u for u, item in manifest.items() if item.get("kind") == "plant"}
    todo = [u for u in plants if not session.is_cached(u)]
    avg_delay = session.base_delay + session.jitter / 2
    to_download = len(todo) if max_plants is None else min(len(todo), max_plants)

    print("\n--- Sitemap summary ---")
    print(f"  Plant URLs in the sitemap            : {len(plants)}")
    print(f"  Already downloaded (cache)           : {len(plants) - len(todo)}")
    print(f"  Missing, to download                 : {len(todo)}")
    print(f"  Plants of the earlier crawl that are not in the sitemap: {len(old_plants - plants.keys())}")
    print(f"  Estimated time for {to_download} downloads    : "
          f"{to_download * avg_delay / 3600:.1f} hours at ~{avg_delay:.1f} s per request")
    if count_only:
        return

    # 3. download the missing plants; cached ones only refresh the manifest
    downloaded, newly, failed = 0, 0, []
    try:
        for url in plants:
            was_cached = session.is_cached(url)
            if not was_cached and max_plants is not None and downloaded >= max_plants:
                continue
            if not was_cached:
                downloaded += 1
                logger.info("Downloading plant %d/%d: %s", downloaded, to_download, url)
            html = session.get(url)
            if html is None:
                failed.append(url)
                continue
            out_path = PAGES_DIR / safe_filename(url)
            if not out_path.exists():
                out_path.write_text(html, encoding="utf-8")
            if not was_cached:
                newly += 1
            manifest[url] = {"url": url, "kind": "plant", "source": "sitemap",
                             "saved_as": str(out_path),
                             "size_bytes": len(html.encode("utf-8"))}
            if not was_cached and downloaded % MANIFEST_FLUSH_EVERY == 0:
                MANIFEST_PATH.write_text(json.dumps(list(manifest.values()), indent=2))
    except RuntimeError as e:
        logger.error("%s", e)

    MANIFEST_PATH.write_text(json.dumps(list(manifest.values()), indent=2))
    (OUT_DIR / "failed_sitemap.txt").write_text("\n".join(failed))
    n_plants = sum(1 for item in manifest.values() if item.get("kind") == "plant")
    print("\n--- Download summary ---")
    print(f"  Newly downloaded      : {newly}")
    print(f"  Failed / disallowed   : {len(failed)}  (see {OUT_DIR / 'failed_sitemap.txt'})")
    print(f"  Plant pages in the manifest: {n_plants}")
    print(f"  Manifest              : {MANIFEST_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crawler for gardenia.net")
    parser.add_argument("--probe", action="store_true",
                        help="1 request: check robots.txt and the genus page structure")
    parser.add_argument("--from-sitemap", action="store_true",
                        help="get the plant URLs from the sitemaps and download the missing ones")
    parser.add_argument("--refresh-sitemap", action="store_true",
                        help="with --from-sitemap: ignore the cached sitemap files")
    parser.add_argument("--dry-run", action="store_true",
                        help="count only: with --from-sitemap read the sitemaps, otherwise "
                             "download index and genus pages")
    parser.add_argument("--max-plants", type=int, default=None,
                        help="download at most N plant pages (trial run)")
    args = parser.parse_args()

    if args.probe:
        probe()
    elif args.from_sitemap:
        crawl_from_sitemap(count_only=args.dry_run, max_plants=args.max_plants,
                           refresh=args.refresh_sitemap)
    else:
        crawl(stage1_only=args.dry_run, max_plants=args.max_plants)
