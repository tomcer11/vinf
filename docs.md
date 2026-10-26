# Vyhľadávanie informácií – dreviny (Trees and Shrubs Online + gardenia.net)

Odovzdanie prvej časti projektu (28. 10. 2026). Kód: [github.com/tomcer11/vinf](https://github.com/tomcer11/vinf).

## 1. Opis projektu

Údaje o drevinách sú roztrúsené. Odborná encyklopédia **Trees and Shrubs Online (TSO)** má
taxonómiu, rozšírenie, habitat, morfológiu a históriu druhov, no o škodcoch a pestovaní píše málo.
Záhradnícka databáza **gardenia.net** má presne to (USDA zóny, škodcovia, pôda, tolerancie,
toxicita), ale aj trvalky, cibuľoviny a trávy. Projekt preto sťahuje obe stránky.

```
crawler/crawl_articles.py ──> crawled_pages/tso/pages/        (TSO: stránky rodov a druhov)
crawler/crawl_gardenia.py ──> crawled_pages/gardenia/pages/   (gardenia: stránky rastlín)
```

| súbor | čo robí |
|---|---|
| `crawler/crawler_config.py` | spoločná zdvorilá HTTP session: robots.txt, oneskorenie, cache, log |
| `crawler/crawl_articles.py`, `crawler/crawl_gardenia.py` | crawlery oboch stránok |

---

## 2. Scrapované stránky

| stránka | čo sa sťahuje | aké dáta sú zaujímavé |
|---|---|---|
| [treesandshrubsonline.org/articles](https://www.treesandshrubsonline.org/articles/) | 26 abecedných zoznamov a–z → stránky rodov a druhov (do úrovne `/articles/<rod>/<druh>/`) | čeľaď, rod, bežné mená, synonymá, rozšírenie (krajiny), habitat, nadmorská výška, morfológia, výška, USDA zóna, RHS, IUCN status, kultivary a ich iné mená, škodcovia a choroby z textu článku |
| [gardenia.net/plants/genera](https://www.gardenia.net/plants/genera) + sitemap | index rodov → stránky rodov → stránky rastlín `/plant/<slug>`; chýbajúce rastliny zo `plant-sitemap*.xml` | typ rastliny, USDA zóna, výška a šírka, expozícia, pôda, tolerancie, láka (vtáky, motýle), toxicita, pôvod, škodcovia a choroby, vedecké synonymá |

---

## 3. Frameworky a knižnice

| knižnica | na čo | prečo |
|---|---|---|
| `requests` | HTTP session s vlastnými hlavičkami a timeoutom | jednoduchá, spoľahlivá; jedna požiadavka naraz stačí (crawl je zámerne pomalý) |
| `urllib.robotparser`, `urllib.parse` | robots.txt, normalizácia URL | štandardná knižnica; robots.txt sa sťahuje s našimi hlavičkami |
| `re` | extrakcia odkazov z HTML a URL zo sitemap | zadanie vyžaduje REGEX; žiadny HTML parser |
| `html`, `json`, `hashlib` | entity v odkazoch, manifest, mená súborov v cache (`sha256(url)`) | štandardná knižnica |

Zámerne **nepoužívam** BeautifulSoup / lxml / Scrapy (odkazy sa hľadajú REGEXom, vlastný crawler
dáva plnú kontrolu nad zdvorilosťou).

---

## 4. Architektúra crawlovacieho systému

Oba crawlery používajú rovnakú triedu `PoliteSession` z `crawler/crawler_config.py`. Každý URL vstúpi do
fronty najviac raz, každá stiahnutá stránka sa uloží do cache, takže zastavený crawl sa dá spustiť
znova bez opätovného sťahovania.

```
                ┌──────────────────────── PoliteSession.get(url) ─────────────────────────┐
 seed URL ─> fronta ─> │ doména povolená? ─> robots.txt can_fetch? ─> v cache? ──áno──> vráti HTML │
 (deque)               │                                                  │nie                  │
   ▲                   │      čakaj 5 s + 0–1 s ─> GET (timeout 5/20 s) ─> zapíš do crawl_log.csv │
   │                   │      200 → ulož do cache   429 → Retry-After / 60 s   403/5xx → chyba    │
   │                   │      5 blokovaní za sebou → stop                                          │
   │                   └────────────────────────────────────────┬────────────────────────────────┘
   │                                                            │ HTML
   │   odkazy (ANCHOR_HREF_RE) len zo stránok zoznamov           ▼
   └──────────────────────────────────────────────────── ulož crawled_pages/<stránka>/pages/*.html + manifest.json
```

* **TSO** (`crawler/crawl_articles.py`): seed = 26 stránok `/articles/a/` … `/articles/z/`. Z nich sa berú
  odkazy pod `/articles/` najviac do úrovne druhu (`/articles/<rod>/<druh>/`); stiahnuté stránky
  rodov a druhov sa už **nerozbaľujú** (hĺbka 1: zoznam → stránka → koniec).
* **gardenia** (`crawler/crawl_gardenia.py`): `/plants/genera` → stránky rodov (aj podrody z bočného panelu)
  → stránky rastlín. Stránka rodu však ukáže len časť rastlín (zvyšok načíta JavaScript z `/refine_by`,
  ktorý robots.txt zakazuje), preto druhý režim číta **sitemap** z robots.txt:
  `sitemap_index.xml` → `plant-sitemap*.xml` → stiahnu sa len chýbajúce rastliny.

---

## 5. Metadáta ukladané pri crawlovaní

**`crawled_pages/tso/manifest.json`, `crawled_pages/gardenia/manifest.json`** – jeden záznam na uloženú stránku:

| pole | príklad (TSO) | príklad (gardenia) |
|---|---|---|
| `url` | `https://www.treesandshrubsonline.org/articles/abelia/abelia-chinensis/` | `https://www.gardenia.net/plant/mazus-reptans` |
| `kind` | – (z hĺbky URL: rod / druh) | `index`, `genus`, `plant` |
| `source` | – | `sitemap` (rastlina doplnená zo sitemap) |
| `saved_as` | `crawled_pages\tso\pages\articles_abelia_abelia-chinensis.html` | `crawled_pages\gardenia\pages\plant_mazus-reptans.html` |
| `size_bytes` | `18071` | `256217` |

**`crawled_pages/tso/crawl_log.csv`, `crawled_pages/gardenia/crawl_log.csv`** – každá požiadavka (aj z cache):

| timestamp | url | status_code | cached | bytes |
|---|---|---|---|---|
| 1791543199.35 | https://www.treesandshrubsonline.org/articles/a/ | 200 | False | 209025 |
| 1791543204.81 | https://www.treesandshrubsonline.org/articles/b/ | 200 | False | 71177 |
| 1792315706.76 | https://www.gardenia.net/plants/genera/abelia | 200 | False | 557862 |

**`crawled_pages/tso/cache/`, `crawled_pages/gardenia/cache/`** – HTML pod menom `sha256(url).html`; podľa neho crawler pozná, čo
už má. Log slúži na štatistiku a kontrolu zdvorilosti (časové odstupy, chybové kódy).

---

## 6. Hlavičky, timeouty a oneskorenie – odôvodnenie

[`crawler/crawler_config.py`, riadky 28–47](https://github.com/tomcer11/vinf/blob/main/crawler/crawler_config.py#L28-L47)

```python
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
```

| nastavenie | hodnota | prečo |
|---|---|---|
| `User-Agent` | `TomasCernegaBot/1.0 (cernega.tomas@gmail.com)` | bot je identifikovateľný a správca stránky vie, koho kontaktovať |
| `From` | `cernega.tomas@gmail.com` | štandardná hlavička pre kontakt na prevádzkovateľa bota |
| oneskorenie | 5 s + náhodne 0–1 s, jedna požiadavka naraz | ≈ 11 požiadaviek za minútu nezaťaží server; jitter zabráni pravidelnému vzoru |
| `Crawl-delay` | z robots.txt, ak je dlhší ako 5 s | pravidlo stránky má prednosť |
| timeout | 5 s spojenie / 20 s čítanie | nezasekne sa na mŕtvom spojení, no stránka gardenie (~330 kB) stihne prísť |
| HTTP 429 | čaká `Retry-After` alebo 60 s (max. 600 s) | server žiada spomaliť |
| 5 blokovaní za sebou | crawler sa zastaví | zablokovaný bot nemá ďalej búšiť do servera |
| robots.txt | stiahnutý s našimi hlavičkami, RFC 9309 (4xx = bez obmedzení, 5xx = všetko zakázané) | `urllib` by ho stiahol so svojím agentom; ošetrené aj jeho chyby (prázdne riadky, `Disallow: /?`) |
| cache | stránka sa nikdy nesťahuje dvakrát | opakovaný beh nezaťaží server |

[`crawler/crawler_config.py`, riadky 191–240](https://github.com/tomcer11/vinf/blob/main/crawler/crawler_config.py#L191-L240)

```python
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
```

---

## 7. Kód: extrakcia URL z HTML

TSO – odkaz `<a … href=…>` v úvodzovkách, apostrofoch aj bez nich; ponechajú sa len odkazy na
rody a druhy:

[`crawler/crawl_articles.py`, riadky 55–112](https://github.com/tomcer11/vinf/blob/main/crawler/crawl_articles.py#L55-L112)

```python
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
```

gardenia – normalizácia URL a výber odkazov podľa regexu cesty (`/plants/genera/<rod>`,
`/plant/<rastlina>`), URL rastlín zo sitemap:

[`crawler/crawl_gardenia.py`, riadky 80–104](https://github.com/tomcer11/vinf/blob/main/crawler/crawl_gardenia.py#L80-L104)

```python
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
```

[`crawler/crawl_gardenia.py`, riadky 231–243](https://github.com/tomcer11/vinf/blob/main/crawler/crawl_gardenia.py#L231-L243)

```python
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
```

---

## 8. Štatistika vycrawlovaných dokumentov

| | Trees and Shrubs Online | gardenia.net |
|---|---:|---:|
| pages in the manifest | 6643 | 10382 |
| pages per kind | genus 930, species 5713, listing a-z 26 | index 1, genus 489, plant 9892 |
| HTML files saved | 6669 | 10382 |
| size of the HTML | 247.1 MB | 3,413.5 MB |
| size on disk (4 KiB clusters) | 260.4 MB | 3,434.9 MB |
| average page | 37 kB | 329 kB |
| cache (files / size) | 6669 / 247.1 MB | 10394 / 3,416.3 MB |
| requests in the crawl log (all runs) | 13321 | 38550 |
| of them HTTP 200 / served from cache | 10941 / 2379 | 10431 / 28118 |

---

## 9. Spustenie

Všetko sa spúšťa z koreňa repozitára:

```
pip install requests
python -m crawler.crawl_articles                  # TSO (berie sa z cache)
python -m crawler.crawl_gardenia --from-sitemap   # gardenia
python -m extractor.extractor                     # -> output/data/trees.jsonl
python -m indexing.tokenizer                      # štatistiky tokenov
python -m indexing.indexer                        # -> output/index/docs.tsv, terms.tsv
python search.py european beech                   # vyhľadávanie, top 10
python -m unittest                                # testy
```
