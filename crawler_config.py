"""
Crawler configuration

This module centralises everything needed to behave like a well-mannered,
identifiable academic bot

Design goals:
- Clearly identifiable User-Agent (bot name + contact email)
- Conservative, configurable rate limiting (delay + optional jitter)
- Respect for robots.txt even though the site doesn't currently have one
  published (re-check at runtime in case that changes)
- Simple on-disk caching so pages are never re-downloaded needlessly
- Logging of every request for your own records / report statistics
"""

import time
import random
import logging
import hashlib
from pathlib import Path
from urllib.parse import urlparse
from urllib import robotparser

import requests

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
BOT_NAME = "TomasCernegaBot"
BOT_VERSION = "1.0"
CONTACT_EMAIL = "cernega.tomas@gmail.com"

USER_AGENT = f"{BOT_NAME}/{BOT_VERSION} ({CONTACT_EMAIL})"
FROM_HEADER = CONTACT_EMAIL

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
# Base delay between requests, in seconds. 3-5s is a reasonable default for
# a small, single-author site like conifers.org.
BASE_DELAY_SECONDS = 5.0
# Random jitter added on top of the base delay, so requests don't land at a
# perfectly predictable interval.
JITTER_SECONDS = 1.0

# Per-request timeout (connect, read)
TIMEOUT = (5, 20)

# Where to cache downloaded pages, so re-running the crawler never
# re-fetches something you already have.
CACHE_DIR = Path("./cache")
CACHE_DIR.mkdir(exist_ok=True)

LOG_FILE = Path("./crawl_log.csv")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("crawler")


class PoliteSession:
    """A requests.Session wrapper that rate-limits and logs every GET."""

    def __init__(self, allowed_domain: str):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "From": FROM_HEADER,
        })
        self.allowed_domain = allowed_domain
        self._last_request_time = 0.0

        # robots.txt.
        self.robots = robotparser.RobotFileParser()
        robots_url = f"https://{allowed_domain}/robots.txt"
        try:
            self.robots.set_url(robots_url)
            self.robots.read()
        except Exception as e:
            logger.warning("Could not read robots.txt (%s): %s", robots_url, e)

        if not LOG_FILE.exists():
            LOG_FILE.write_text("timestamp,url,status_code,cached,bytes\n")

    def _wait(self):
        elapsed = time.time() - self._last_request_time
        delay = BASE_DELAY_SECONDS + random.uniform(0, JITTER_SECONDS)
        remaining = delay - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_time = time.time()

    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()
        return CACHE_DIR / f"{h}.html"

    def _log(self, url, status_code, cached, nbytes):
        with LOG_FILE.open("a") as f:
            f.write(f"{time.time()},{url},{status_code},{cached},{nbytes}\n")

    def get(self, url: str) -> str | None:
        """Fetch a URL, respecting robots.txt, cache, and rate limits.

        Returns the page text, or None if disallowed / failed.
        """
        domain = urlparse(url).netloc
        if domain != self.allowed_domain:
            logger.warning("Refusing to fetch out-of-scope domain: %s", url)
            return None

        if not self.robots.can_fetch(USER_AGENT, url):
            logger.warning("Disallowed by robots.txt: %s", url)
            return None

        cache_path = self._cache_path(url)
        if cache_path.exists():
            text = cache_path.read_text(encoding="utf-8", errors="replace")
            self._log(url, "cached", True, len(text))
            return text

        self._wait()
        try:
            resp = self.session.get(url, timeout=TIMEOUT)
        except requests.RequestException as e:
            logger.error("Request failed for %s: %s", url, e)
            self._log(url, "error", False, 0)
            return None

        self._log(url, resp.status_code, False, len(resp.content))

        if resp.status_code == 429:
            # Back off hard if the server tells us to slow down.
            logger.warning("Got 429 for %s — backing off for 60s", url)
            time.sleep(60)
            return None

        if resp.status_code != 200:
            logger.warning("Non-200 status %s for %s", resp.status_code, url)
            return None

        cache_path.write_text(resp.text, encoding="utf-8")
        return resp.text


if __name__ == "__main__":
    # Smoke test: fetch one alphabetical listing page once.
    s = PoliteSession(allowed_domain="www.treesandshrubsonline.org")
    html = s.get("https://www.treesandshrubsonline.org/articles/a/")
    if html:
        print(f"Fetched {len(html)} characters.")
        print(f"User-Agent in use: {USER_AGENT}")
