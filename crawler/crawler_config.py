"""
Crawler configuration, shared by crawl_articles.py and crawl_gardenia.py.

Everything needed to behave like a well-mannered, identifiable bot:
- User-Agent and From headers with a contact address
- robots.txt is downloaded with our own headers (not with urllib's default
  agent), obeyed, and its Crawl-delay is respected when it is longer than ours
- delay + jitter between requests, one request at a time
- on-disk cache so a page is never downloaded twice
- back-off on HTTP 429 (Retry-After is honoured) and a stop after several
  blocking responses in a row, so a blocked bot does not keep hammering a site
- every request is logged to a CSV file
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
# Rate limiting and defaults
# ---------------------------------------------------------------------------
BASE_DELAY_SECONDS = 5.0      # minimum delay between requests
JITTER_SECONDS = 1.0          # random extra delay of 0 .. JITTER_SECONDS
TIMEOUT = (5, 20)             # (connect, read) seconds

CACHE_DIR = Path("./crawled_pages/tso/cache")   # defaults used by crawl_articles.py
LOG_FILE = Path("./crawled_pages/tso/crawl_log.csv")

BACKOFF_SECONDS = 60          # wait after HTTP 429 without Retry-After
MAX_BACKOFF_SECONDS = 600
MAX_CONSECUTIVE_FAILURES = 5  # 403 / 429 / 5xx / network errors in a row

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("crawler")


def _prepare_robots_lines(text: str):
    """Make robots.txt readable for urllib.robotparser, which deviates from the
    standard in two ways:
    - it ends a group at the first blank line, so every rule after a blank
      line or a comment line is silently ignored (gardenia.net: 44 of 108
      Disallow rules were used). Blank and comment-only lines are removed.
    - it stores "Disallow: /?" as "Disallow: /", which blocks the whole site,
      although the rule only concerns URLs that start with "/?" (the home page
      with a query string). Such lines are removed; this crawler never requests
      URLs with a query string.
    Returns (lines, dropped_rules)."""
    kept, dropped = [], []
    for line in text.splitlines():
        rule = line.split("#", 1)[0].strip()
        if not rule:
            continue
        field, _, value = rule.partition(":")
        if field.strip().lower() in ("allow", "disallow") and value.strip().startswith("/?"):
            dropped.append(rule)
        else:
            kept.append(rule)
    return kept, dropped


class PoliteSession:
    """A requests.Session wrapper that obeys robots.txt, rate-limits,
    caches and logs every GET."""

    def __init__(self, allowed_domain: str, cache_dir=CACHE_DIR, log_file=LOG_FILE,
                 base_delay: float = BASE_DELAY_SECONDS,
                 jitter: float = JITTER_SECONDS):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "From": FROM_HEADER,
        })
        self.allowed_domain = allowed_domain
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.base_delay = base_delay
        self.jitter = jitter
        self._last_request_time = 0.0
        self._consecutive_failures = 0

        self.robots = robotparser.RobotFileParser()
        self.robots_status = None   # HTTP status of robots.txt, None = no answer
        self.robots_text = ""       # its text when the status was 200
        self.robots_error = ""      # why it could not be fetched
        self._load_robots()

        if not self.log_file.exists():
            self.log_file.write_text("timestamp,url,status_code,cached,bytes\n")

    # -- robots.txt ---------------------------------------------------------
    def _load_robots(self):
        """Download robots.txt with our own headers and parse it.

        RobotFileParser.read() would use urllib's default agent, and a 403 for
        that agent makes it forbid the whole site. Following RFC 9309:
        200 = parse it, other 4xx = no restrictions, 5xx or no answer =
        assume everything is disallowed.
        """
        robots_url = f"https://{self.allowed_domain}/robots.txt"
        try:
            resp = self.session.get(robots_url, timeout=TIMEOUT)
        except requests.RequestException as e:
            logger.error("Could not fetch %s (%s). Assuming everything is disallowed.",
                         robots_url, e)
            self.robots_error = str(e)
            self.robots.disallow_all = True
            return

        self.robots_status = resp.status_code
        if resp.status_code == 200:
            self.robots_text = resp.text
            lines, dropped = _prepare_robots_lines(resp.text)
            if dropped:
                logger.info("Ignored robots.txt rule(s) that urllib misreads as \"block everything\": %s", dropped)
            self.robots.parse(lines)
            logger.info("robots.txt loaded from %s", robots_url)
        elif 400 <= resp.status_code < 500:
            logger.warning("%s returned %s, treating it as no restrictions",
                           robots_url, resp.status_code)
            self.robots.allow_all = True
        else:
            logger.error("%s returned %s. Assuming everything is disallowed.",
                         robots_url, resp.status_code)
            self.robots.disallow_all = True
            return

        crawl_delay = self.robots.crawl_delay(USER_AGENT)
        if crawl_delay and crawl_delay > self.base_delay:
            logger.info("robots.txt Crawl-delay is %s s, using it instead of %s s",
                        crawl_delay, self.base_delay)
            self.base_delay = float(crawl_delay)

    # -- helpers ------------------------------------------------------------
    def _wait(self):
        elapsed = time.time() - self._last_request_time
        delay = self.base_delay + random.uniform(0, self.jitter)
        remaining = delay - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_time = time.time()

    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()
        return self.cache_dir / f"{h}.html"

    def is_cached(self, url: str) -> bool:
        return self._cache_path(url).exists()

    def _log(self, url, status_code, cached, nbytes):
        with self.log_file.open("a") as f:
            f.write(f"{time.time()},{url},{status_code},{cached},{nbytes}\n")

    def _register_failure(self):
        self._consecutive_failures += 1
        if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            raise RuntimeError(
                f"{self._consecutive_failures} blocking responses in a row "
                f"(403 / 429 / 5xx / network errors). Stopping so the site is not "
                f"hammered. Downloaded pages are kept in the cache; restart later."
            )

    @staticmethod
    def _retry_after(resp) -> int:
        value = resp.headers.get("Retry-After", "")
        if value.isdigit():
            return min(int(value), MAX_BACKOFF_SECONDS)
        return BACKOFF_SECONDS

    # -- main entry point ---------------------------------------------------
    def get(self, url: str) -> str | None:
        """Fetch a URL, respecting robots.txt, cache and rate limits.

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
            self._register_failure()
            return None

        self._log(url, resp.status_code, False, len(resp.content))

        if resp.status_code == 429:
            wait = self._retry_after(resp)
            logger.warning("Got 429 for %s, backing off for %ss", url, wait)
            time.sleep(wait)
            self._register_failure()
            return None

        if resp.status_code == 403 or resp.status_code >= 500:
            logger.warning("Status %s for %s", resp.status_code, url)
            self._register_failure()
            return None

        if resp.status_code != 200:
            logger.warning("Non-200 status %s for %s", resp.status_code, url)
            return None

        self._consecutive_failures = 0
        cache_path.write_text(resp.text, encoding="utf-8")
        return resp.text


if __name__ == "__main__":
    s = PoliteSession(allowed_domain="www.treesandshrubsonline.org")
    html = s.get("https://www.treesandshrubsonline.org/articles/a/")
    if html:
        print(f"Fetched {len(html)} characters.")
        print(f"User-Agent in use: {USER_AGENT}")
