"""
Crawler for treesandshrubsonline.org/articles

Scope:
- Start at https://www.treesandshrubsonline.org/articles/
- Visit the 26 alphabetical listing pages /articles/a/ ... /articles/z/
- From each listing page take every link under /articles/ that is at most
  genus/species level, found with a regular expression (no HTML parsing library):
    /articles/arctostaphylos/                                  -> taken
    /articles/arctostaphylos/arctostaphylos-uva-ursi/          -> taken (deepest)
    /articles/arctostaphylos/arctostaphylos-uva-ursi/arctostaphylos-uva-ursi-a-pumila/
                                                               -> skipped (too deep)
- Each linked page is downloaded and saved, but its content is NEVER searched
  for further links (strict depth 1: listing page -> page -> stop)
- Pages already stored in the on-disk cache are not downloaded again

Identification:
  User-Agent: TomasCernegaBot/1.0 (cernega.tomas@gmail.com)
  From: cernega.tomas@gmail.com

Delay: 5 s + up to 1 s jitter between requests (see crawler_config.py)

Usage:
  python -m crawler.crawl_articles --dry-run   # count links, no page downloads
  python -m crawler.crawl_articles             # full crawl (safe to stop and restart)
"""

import hashlib
import html as htmllib
import json
import re
import string
import sys
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse

from crawler.crawler_config import PoliteSession, logger, BASE_DELAY_SECONDS, JITTER_SECONDS

DOMAIN = "www.treesandshrubsonline.org"
BASE = f"https://{DOMAIN}"
ARTICLES_BASE = f"{BASE}/articles"

PAGES_DIR = Path("./crawled_pages/tso/pages")
PAGES_DIR.mkdir(parents=True, exist_ok=True)

MANIFEST_PATH = Path("./crawled_pages/tso/manifest.json")
MANIFEST_FLUSH_EVERY = 500

# Deepest allowed URL: /articles/<genus>/<species>/  -> 3 path segments.
MAX_PATH_SEGMENTS = 3

STATS = {"skipped_too_deep": 0}

# Finds the href of every <a ...> tag. Handles double quotes, single quotes
# and unquoted values, other attributes before or after href, upper or lower
# case, and tags spread over several lines. "data-href" is not matched.
ANCHOR_HREF_RE = re.compile(
    r"""<a\b[^>]*?(?<![\w-])href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""",
    re.IGNORECASE | re.DOTALL,
)


def listing_urls() -> list[str]:
    """The 26 starting points of the crawl, one per letter."""
    return [f"{ARTICLES_BASE}/{letter}/" for letter in string.ascii_lowercase]


def extract_links(html: str, page_url: str) -> list[str]:
    """Every link under /articles/ found on a listing page, down to species level.

    Dropped links:
    - other domains, and other sections of the site (/resources/, /about/ ...)
    - the /articles/ index itself and the 26 a-z listing pages
      (they are seeded separately)
    - URLs deeper than /articles/<genus>/<species>/
    - the page itself
    """
    letter_paths = {f"/articles/{letter}/" for letter in string.ascii_lowercase}
    links = []
    seen = set()

    for match in ANCHOR_HREF_RE.finditer(html):
        raw = match.group(1) or match.group(2) or match.group(3)
        if not raw:
            continue

        href = urljoin(page_url, htmllib.unescape(raw.strip())).split("#")[0]
        parsed = urlparse(href)

        if parsed.netloc != DOMAIN:
            continue
        if not parsed.path.startswith("/articles/"):
            continue

        norm_path = parsed.path if parsed.path.endswith("/") else parsed.path + "/"
        if norm_path == "/articles/" or norm_path in letter_paths:
            continue
        if href.rstrip("/") == page_url.rstrip("/"):
            continue

        # Depth limit: "articles" + genus + species = 3 segments.
        segments = [seg for seg in norm_path.split("/") if seg]
        if len(segments) > MAX_PATH_SEGMENTS:
            STATS["skipped_too_deep"] += 1
            continue

        if href not in seen:
            seen.add(href)
            links.append(href)

    return links


def safe_filename(url: str) -> str:
    path = urlparse(url).path.strip("/")
    name = path.replace("/", "_") or "index"
    if len(name) > 180:  # keep file names within filesystem limits
        name = name[:150] + "_" + hashlib.sha1(url.encode()).hexdigest()[:10]
    return name + ".html"


def dry_run():
    """Count the links on the 26 listing pages without downloading any of the
    linked pages. Listing pages already in the cache cost no requests."""
    session = PoliteSession(allowed_domain=DOMAIN)
    all_links = set()
    per_letter = {}

    for url in listing_urls():
        letter = url.rstrip("/").rsplit("/", 1)[-1]
        html = session.get(url)
        if html is None:
            per_letter[letter] = None
            continue
        links = extract_links(html, url)
        per_letter[letter] = len(links)
        all_links.update(links)

    cached = sum(1 for u in all_links if session._cache_path(u).exists())
    todo = len(all_links) - cached
    avg_delay = BASE_DELAY_SECONDS + JITTER_SECONDS / 2

    print("\n--- Dry-run summary ---")
    for letter, count in per_letter.items():
        print(f"  {letter}: {count if count is not None else 'FAILED'}")
    print(f"  Unique pages in scope : {len(all_links)}")
    print(f"  Already cached        : {cached}")
    print(f"  Still to download     : {todo}")
    print(f"  Estimated time        : {todo * avg_delay / 3600:.1f} hours "
          f"at ~{avg_delay:.1f} s per request")
    print(f"  Skipped (too deep)    : {STATS['skipped_too_deep']} anchors")


def write_manifest(manifest: list[dict]):
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


def run():
    session = PoliteSession(allowed_domain=DOMAIN)

    # Queue of (url, kind). "listing" pages are expanded (their links are
    # appended as "page"); "page" items are saved and never expanded.
    queue = deque((url, "listing") for url in listing_urls())
    visited = set()
    manifest = []

    while queue:
        url, kind = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        logger.info("Fetching [%s]: %s (%d left in queue)", kind, url, len(queue))
        html = session.get(url)  # served from cache if already downloaded
        if html is None:
            logger.warning("Failed to fetch: %s", url)
            continue

        out_path = PAGES_DIR / safe_filename(url)
        out_path.write_text(html, encoding="utf-8")

        if kind == "listing":
            links = extract_links(html, url)
            logger.info("  listing page yielded %d links", len(links))
            for link in links:
                if link not in visited:
                    queue.append((link, "page"))
        else:
            # kind == "page": save only, do NOT look at its links.
            manifest.append({
                "url": url,
                "saved_as": str(out_path),
                "size_bytes": len(html.encode("utf-8")),
            })
            if len(manifest) % MANIFEST_FLUSH_EVERY == 0:
                write_manifest(manifest)

    write_manifest(manifest)
    logger.info("Skipped %d anchors deeper than species level", STATS["skipped_too_deep"])
    logger.info("Done. %d pages saved (plus 26 listing pages). Manifest: %s",
                len(manifest), MANIFEST_PATH)
    print(f"\nTotal pages saved: {len(manifest)}")
    print(f"Manifest written to: {MANIFEST_PATH}")


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        dry_run()
    else:
        run()
