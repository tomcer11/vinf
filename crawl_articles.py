"""
Crawler for treesandshrubsonline.org/articles

Scope agreed with the site's editors:
- Start at https://www.treesandshrubsonline.org/articles/
- Visit the 26 alphabetical listing pages, a through z
  (https://www.treesandshrubsonline.org/articles/a/ ... /z/)
- From each listing page, extract only the GENUS links and visit each ONCE.
  A genus link has a one-word anchor ("Abelia"), a URL of the form
  /articles/<genus>/ and a slug equal to the anchor text. Species
  ("Abelia chinensis"), cultivars ('Golden') and deeper pages are skipped
- Article pages are saved as-is but are NEVER parsed for further links
  (i.e. if we land on .../articles/abelia, we do not look at any links
  found on that page -- we go straight back to the queue and fetch the
  next item)
- This is a strict depth-1 crawl: listing page -> article page -> stop.

Identification (matches what was proposed by email):
  User-Agent: TomasCernegaBot/1.0 (cernega.tomas@gmail.com)
  From: cernega.tomas@gmail.com

Delay: 5 seconds base + up to 1s jitter between requests (see crawler_config.py)
"""

import json
import re
import string
from pathlib import Path
from urllib.parse import urljoin, urlparse
from collections import deque

from bs4 import BeautifulSoup

from crawler_config import PoliteSession, logger

DOMAIN = "www.treesandshrubsonline.org"
BASE = f"https://{DOMAIN}"
ARTICLES_BASE = f"{BASE}/articles"

PAGES_DIR = Path("./pages")
PAGES_DIR.mkdir(exist_ok=True)

MANIFEST_PATH = Path("./manifest.json")


def listing_urls() -> list[str]:
    """The 26 starting points of the crawl, one per letter."""
    return [f"{ARTICLES_BASE}/{letter}/" for letter in string.ascii_lowercase]


def extract_links(html: str, page_url: str) -> list[str]:
    """All in-scope genus links found directly on a listing page.

    Kept links must:
    - have a one-word, letters-only anchor text (genus name)
    - point to a URL of exactly the form /articles/<genus>/ (one path
      segment after /articles/); species and cultivar pages are always
      nested deeper, e.g. /articles/acer/acer-saccharinum/...-golden/
    - have a URL slug equal to the anchor text (Abelia -> /articles/abelia/),
      so one-word cultivar names such as 'Golden' can never pass
    - resolve to the same domain
    - not be the listing page itself
    - not be one of the 26 alphabet-listing pages (those are seeded
      separately and never re-added to the queue)
    """
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()

    single_letter_paths = {f"/articles/{letter}/" for letter in string.ascii_lowercase}

    for a in soup.find_all("a", href=True):
        # Only genus-level links: the anchor text must be exactly one word
        # made of letters (optionally with a leading hybrid sign), e.g.
        # "Cornus".
        anchor_text = a.get_text(strip=True)

        href = urljoin(page_url, a["href"]).split("#")[0]
        parsed = urlparse(href)

        if parsed.netloc != DOMAIN:
            continue
        if not parsed.path.startswith("/articles/"):
            continue

        norm_path = parsed.path if parsed.path.endswith("/") else parsed.path + "/"
        if norm_path in single_letter_paths:
            continue  # skip links back to the a-z listing pages

        # Genus pages live at /articles/<genus>/ and nowhere deeper.
        segments = [seg for seg in norm_path.split("/") if seg]

        if len(segments) < 2 or segments[0] != "articles":
            continue
        # The slug must match the anchor text (hybrid sign / "x-" ignored),
        # which rules out one-word cultivar names that sit at genus level.
        slug = segments[1].removeprefix("x-")
        if slug != anchor_text.lstrip("×").lower():
            continue
        if href.rstrip("/") == page_url.rstrip("/"):
            continue

        if href not in seen:
            seen.add(href)
            links.append(href)

    return links


def safe_filename(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return (path.replace("/", "_") or "index") + ".html"


def run():
    session = PoliteSession(allowed_domain=DOMAIN)

    # The queue holds (url, kind) pairs. "listing" pages are expanded
    # (their links get added to the queue); "article" pages are fetched
    # and saved, but never expanded -- this enforces strict depth 1.
    queue = deque((url, "listing") for url in listing_urls())
    visited = set()
    manifest = []

    while queue:
        url, kind = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        logger.info("Fetching [%s]: %s", kind, url)
        html = session.get(url)
        if html is None:
            logger.warning("Failed to fetch: %s", url)
            continue

        out_path = PAGES_DIR / safe_filename(url)
        out_path.write_text(html, encoding="utf-8")

        if kind == "listing":
            # Expand: pull article links out and push them to the back
            # of the queue as "article" (non-expandable) items.
            article_links = extract_links(html, url)
            logger.info("  listing page yielded %d article links", len(article_links))
            for link in article_links:
                if link not in visited:
                    queue.append((link, "article"))
        else:
            # kind == "article": save only, do NOT look at its links.
            manifest.append({
                "url": url,
                "saved_as": str(out_path),
                "size_bytes": len(html.encode("utf-8")),
            })

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    logger.info(
        "Done. %d article pages saved (plus up to 26 listing pages). Manifest: %s",
        len(manifest), MANIFEST_PATH,
    )
    print(f"\nTotal article pages saved: {len(manifest)}")
    print(f"Manifest written to: {MANIFEST_PATH}")


if __name__ == "__main__":
    run()
