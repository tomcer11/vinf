"""
REGEX extractor for the pages downloaded by crawl_articles.py and crawl_gardenia.py

Every saved page becomes one JSON record. The data are found in the HTML only
with regular expressions (module re), no HTML parsing library is used.

Input (the manifests written by the crawlers):
  manifest.json            Trees and Shrubs Online (TSO): genus and species pages
  gardenia/manifest.json   gardenia.net: plant pages (index and genus pages are skipped)

Output:
  data/tso.jsonl           one record per TSO page
  data/gardenia.jsonl      one record per gardenia plant page

Two kinds of extractors:
- page extractors (TSO_*_RE, GARDENIA_*_RE): cut a field out of the HTML
  (title, family, distribution, the "Requirements" table ...)
- text extractors (ZONE_RE, HEIGHT_RE, ALTITUDE_RE, PEST_PATTERNS ...): find a
  value in the plain text of a field (hardiness zone range, height in metres,
  altitude, pests and diseases, sentences about the habitat, synonyms)

Usage:
  python extractor.py                     # both sites
  python extractor.py --site tso          # only one site (tso | gardenia)
  python extractor.py --show pages/articles_picea_picea-abies.html
                                          # print the record of one page
"""

import argparse
import html as htmllib
import json
import re
import sys
import time
from multiprocessing import Pool
from pathlib import Path
from urllib.parse import urlparse

DATA_DIR = Path("./data")
TSO_MANIFEST = Path("./manifest.json")
GARDENIA_MANIFEST = Path("./gardenia/manifest.json")
TSO_OUT = DATA_DIR / "tso.jsonl"
GARDENIA_OUT = DATA_DIR / "gardenia.jsonl"

MAX_EVIDENCE = 5          # sentences kept as evidence for a canonical pest
MAX_EVIDENCE_CHARS = 320
MAX_PEST_SENTENCES = 40   # sentences about any pest or disease
MAX_HABITAT_SENTENCES = 8

# ---------------------------------------------------------------------------
# HTML -> text
# ---------------------------------------------------------------------------
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# data-caption="<p>...</p>" holds HTML inside an attribute; it would end the
# tag at the wrong ">" and leave half a tag in the text
DATA_ATTR_RE = re.compile(r"""\sdata-[\w-]+=(?:"[^"]*"|'[^']*')""")
# tags that end a block of text; they become a line break so that list items
# and paragraphs without a full stop are not glued into one sentence
BLOCK_TAG_RE = re.compile(r"</?(?:p|li|ul|ol|br|tr|td|th|h[1-6]|div|hr|table|tbody)\b[^>]*>",
                          re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
SPACES_RE = re.compile(r"[^\S\n]+")
NEWLINES_RE = re.compile(r"\s*\n\s*")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(‘'\"])")
# a full stop after these is not the end of a sentence:
# "mountains of S.E. Spain", "Mt. Omei", "Bot. Mag.", "var. Glauca"
ABBREVIATION_RE = re.compile(
    r"(?:\b[A-Z]\.|\b(?:Mt|St|Bot|Mag|Fl|Fig|No|Vol|Dr|Prof|Mr|Mrs|var|subsp|ssp|spp|cf|al|cv|agg|ed|pp)\.)$")


def clean(fragment: str) -> str:
    """HTML fragment -> plain text: tags removed, entities decoded, white space
    collapsed. Block tags become line breaks."""
    if not fragment:
        return ""
    text = COMMENT_RE.sub(" ", fragment)
    text = DATA_ATTR_RE.sub("", text)
    text = BLOCK_TAG_RE.sub("\n", text)
    text = TAG_RE.sub("", text)
    text = htmllib.unescape(text)
    text = SPACES_RE.sub(" ", text)
    return NEWLINES_RE.sub("\n", text).strip()


def one_line(text: str) -> str:
    return SPACES_RE.sub(" ", text.replace("\n", " ")).strip()


def sentences(text: str) -> list[str]:
    """Split into sentences; a line break always ends one."""
    out = []
    for line in (text or "").split("\n"):
        pending = ""
        for piece in SENTENCE_SPLIT_RE.split(line):
            pending = f"{pending} {piece}" if pending else piece
            if not ABBREVIATION_RE.search(pending):
                out.append(pending.strip())
                pending = ""
        if pending:
            out.append(pending.strip())
    return [s for s in out if s]


def first(regex: re.Pattern, text: str, group: int = 1) -> str | None:
    m = regex.search(text)
    return m.group(group) if m else None


# ---------------------------------------------------------------------------
# Scientific names
# ---------------------------------------------------------------------------
# "Picea abies", "Abelia × grandiflora", "Picea pungens var. glauca",
# "Acer palmatum 'Bloodgood'", "×Mahoberberis aquisargentii", "Rosa 'Peace'"
SCI_NAME_RE = re.compile(
    r"""^\s*
    (?P<genus>[×x+]?\s?[A-Z][a-zë-]+)                     # genus, maybe an intergeneric hybrid or graft chimaera
    (?:\s+(?P<hybrid>[×x])(?=\s))?                         # hybrid sign before the epithet
    (?:\s+(?P<epithet>(?!var\.|subsp\.|ssp\.|f\.|cv\.)[a-zë][a-zë-]+\.?))?   # species epithet
    (?:\s+(?P<rank>subsp\.|ssp\.|var\.|f\.|forma)\s+(?P<infra>[a-zë][a-zë-]+))?   # infraspecific taxon
    """,
    re.VERBOSE,
)
# cultivar name in quotes: 'Nana', ‘Nana’, "Nana"
CULTIVAR_RE = re.compile(r"""['‘’"]([^'‘’"]{2,60})['‘’"]""")


def parse_sci_name(name: str) -> dict:
    """Split a plant name into genus / hybrid / epithet / rank / infra / cultivar,
    all lower case. Returns {} when no genus is found."""
    name = htmllib.unescape(name or "").replace(" ", " ")
    m = SCI_NAME_RE.match(name)
    if not m:
        return {}
    genus = m.group("genus").replace(" ", "").lower().lstrip("x×+")
    epithet = m.group("epithet")
    if epithet in ("aggregate", "agg.", "cultivars", "hybrids", "group"):
        epithet = None
    parts = {
        "genus": genus,
        "hybrid": bool(m.group("hybrid")),
        "epithet": epithet.rstrip(".") if epithet else None,
        "rank": m.group("rank"),
        "infra": m.group("infra"),
        "cultivar": None,
    }
    cultivar = CULTIVAR_RE.search(name)
    if cultivar:
        parts["cultivar"] = cultivar.group(1).strip().lower()
    return parts


# ---------------------------------------------------------------------------
# Text extractors shared by both sites
# ---------------------------------------------------------------------------
# USDA hardiness zones: "4", "8b", "8-9", "8b-9a", "3 - 8", "7 to 10"
ZONE_RE = re.compile(r"\b(\d{1,2})([ab])?(?:\s*(?:–|-|to)\s*(\d{1,2})([ab])?)?\b")


def parse_zones(raw: str | None) -> dict | None:
    """'8b-9a' -> {'raw': '8b-9a', 'min': 8, 'max': 9}. A single value is the
    coldest zone the plant survives ('hardy to zone 4'), so 'max' is None."""
    if not raw:
        return None
    m = ZONE_RE.search(raw)
    if not m:
        return None
    low = int(m.group(1))
    high = int(m.group(3)) if m.group(3) else None
    if not 1 <= low <= 13 or (high is not None and not low <= high <= 13):
        return None
    return {"raw": one_line(raw), "min": low, "max": high}


# height at the start of a description: "Tree 40–60 m tall", "Shrub to 3 m",
# "Shrub or small tree, 2–5 m", "Shrub 30–80 cm", "Tree 30–40(–60) m tall"
# (the number in brackets is an exceptional maximum); the older articles from
# Bean's book use feet: "A tree varying in height from 60 to over 100 ft"
HEIGHT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)(?:\s*(?:–|-|to|or)\s*(?:over |about |c\. )?(\d+(?:[.,]\d+)?))?"
    r"(?:\s*\((?:–|-)\s*(\d+(?:[.,]\d+)?)\))?"
    r"\s*(m|cm|ft|feet)\b(?!\s*(?:dbh|girth|wide|across|in diameter))",
)
UNIT_TO_M = {"m": 1.0, "cm": 0.01, "ft": 0.3048, "feet": 0.3048}
LIFE_FORM_RE = re.compile(r"\b(tree|shrub|subshrub|climber|liana|vine|scrambler)s?\b", re.IGNORECASE)
LEAF_HABIT_RE = re.compile(r"\b(evergreen|semi-evergreen|deciduous)\b", re.IGNORECASE)


def parse_height(text: str) -> dict | None:
    m = HEIGHT_RE.search(text or "")
    if not m:
        return None
    factor = UNIT_TO_M[m.group(4)]
    low = float(m.group(1).replace(",", ".")) * factor
    high = m.group(3) or m.group(2)
    high = float(high.replace(",", ".")) * factor if high else low
    if high < low or high > 150:
        return None
    return {"raw": m.group(0), "min_m": round(low, 2), "max_m": round(high, 2)}


# altitude in a habitat text: "1,300–2,600 m", "to 1500 m asl", "at 3000 m",
# "rarely descending below 5,000 ft"; "60 ft high" is a height, not an altitude
ALTITUDE_RE = re.compile(
    r"(\d{1,2},\d{3}|\d{3,5})(?:\s*(?:–|-|to)\s*(\d{1,2},\d{3}|\d{3,5}))?\s*(m|ft|feet)\b(?!m)"
    r"(?!\s*(?:high|tall|in height|long|wide|across|in girth|girth))"
)


def parse_altitude(text: str) -> dict | None:
    values = []
    for m in ALTITUDE_RE.finditer(text or ""):
        for g in (m.group(1), m.group(2)):
            if g:
                value = round(int(g.replace(",", "")) * UNIT_TO_M[m.group(3)])
                if 0 < value < 6500:
                    values.append(value)
    if not values:
        return None
    return {"min_m": min(values), "max_m": max(values)}


# mountain environment named in a habitat text, also by the name of a range
MOUNTAIN_RE = re.compile(
    r"\b(mountains?|mountainous|montane|alpine|sub-?alpine|highlands?|uplands?|ridges?|"
    r"summits?|peaks?|cliffs?|screes?|tree ?line|timberline|limit of tree growth|"
    r"Alps|Pyrenees|Carpathians|Tatras?|Apennines|Himalayas?|Andes|Rockies|"
    r"Appalachians|Urals|Altai|Dolomites|Tian Shan|Hindu Kush|Karakoram|Sierra Nevada)\b",
    re.IGNORECASE,
)
MOUNTAIN_MIN_ALTITUDE = 1000   # habitat reaching this altitude counts as mountain

# sentences of a long text that describe where the plant grows in the wild:
# "Native of the Alps", "grows in swamps", "in montane rainforest of Queensland"
HABITAT_SENTENCE_RE = re.compile(
    r"\b(native (?:of|to)|grows? (?:in|on|at)|growing (?:in|on|at)|found (?:in|on|at)|"
    r"occurs? in|in the wild|wild (?:in|on)|"
    r"at (?:an )?(?:altitudes?|elevations?) of|(?:altitudes?|elevations?) (?:of|from|between))\b"
    r"|\b(?:in|on|along|by|near|among|amongst) (?:[\w-]+ ){0,3}"
    r"(?:forests?|rain ?forests?|woodlands?|woods|thickets?|scrub|swamps?|bogs?|marshes|fens?|"
    r"grasslands?|meadows?|prairies?|deserts?|savann?as?|steppes?|stream ?sides?|streams|"
    r"river ?banks?|rivers|coasts?|cliffs?|ravines?|gorges?|canyons?|valleys?|slopes?|hillsides?|dunes?)\b",
    re.IGNORECASE,
)
# "planted in the woodland garden at Wakehurst" is about cultivation, not the wild
HABITAT_SKIP_RE = re.compile(r"\b(?:gardens?|arboret(?:um|a)|cultivat\w+|planted|nurser(?:y|ies)|parks?)\b",
                             re.IGNORECASE)
NATIVE_OF_RE = re.compile(r"\bnative (?:of|to)\b", re.IGNORECASE)

# canonical pest or disease -> regex. Words with other meanings ("scale" of a
# cone, "rust-coloured") are only matched in a pest sense.
PEST_PATTERNS = {
    "aphid": r"\b(?:woolly )?aphids?\b|\bgreenfl(?:y|ies)\b|\bblackfl(?:y|ies)\b",
    "adelgid": r"\badelgids?\b|\bAdelges\b",
    "scale insect": r"\bscale insects?\b|\bscales? \(insects?\)|\b(?:soft|hard|armou?red|cottony|oystershell|euonymus) scales?\b",
    "spider mite": r"\b(?:red )?spider mites?\b|\bred spider\b",
    "mite": r"\b(?:gall|bud|rust|eriophyid) mites?\b",
    "mealybug": r"\bmealy ?bugs?\b",
    "whitefly": r"\bwhite ?fl(?:y|ies)\b",
    "thrips": r"\bthrips\b",
    "caterpillar": r"\bcaterpillars?\b|\blarvae of (?:the )?\w+ moths?\b",
    "moth": r"\b(?:gypsy|winter|leopard|tortrix|box tree|codling|tent|ermine|clearwing|goat) moths?\b",
    "sawfly": r"\bsawfl(?:y|ies)\b",
    "beetle": r"\b(?:bark|leaf|ambrosia|longhorn|Japanese|elm bark|ash borer|viburnum) beetles?\b",
    "borer": r"\bborers?\b|\bEmerald Ash Borer\b",
    "weevil": r"\bweevils?\b",
    "leaf miner": r"\bleaf[- ]?miners?\b",
    "gall": r"\bgall (?:wasps?|midges?|mites?)\b|\bgalls\b",
    "slug and snail": r"\bslugs?\b|\bsnails?\b",
    "deer": r"\b(?:browsed|browsing|eaten|damaged?|grazed)\b[^.]{0,40}\bdeer\b|\bdeer\b[^.]{0,30}\b(?:browse|browsing|damage|eat|graze|graz)",
    "honey fungus": r"\bhoney fungus\b|\bArmillaria\b",
    "phytophthora": r"\bPhytophthora\b|\bsudden oak death\b",
    "root rot": r"\broot rots?\b|\bcrown rots?\b|\bheart ?rots?\b",
    "powdery mildew": r"\bpowdery mildews?\b|\bmildews?\b",
    "rust": r"\brust(?:s| fungus| fungi| disease)\b|\b(?:blister|cedar[- ]apple|needle|leaf|poplar|pear) rusts?\b",
    "canker": r"\bcankers?\b",
    "fireblight": r"\bfire ?blight\b",
    "blight": r"\b(?:leaf|needle|shoot|twig|chestnut|box|petal|tip) blights?\b|\bblights?\b",
    "dieback": r"\bdie-?back\b|\bHymenoscyphus\b|\bChalara\b",
    "wilt": r"\b(?:verticillium|fusarium|oak) wilts?\b|\bwilt disease\b",
    "dutch elm disease": r"\bDutch elm disease\b",
    "leaf spot": r"\bleaf[- ]spots?\b|\banthracnose\b|\bblack ?spot\b",
    "scab": r"\bscab\b",
    "sooty mould": r"\bsooty mou?lds?\b",
    "grey mould": r"\bgr[ae]y mou?lds?\b|\bBotrytis\b",
    "coral spot": r"\bcoral spot\b",
    "silver leaf": r"\bsilver ?leaf\b(?! \w*maple)",
    "mistletoe": r"\bmistletoes?\b",
}
PEST_RES = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in PEST_PATTERNS.items()}
# all of them in one regex: one search per sentence instead of 37
PEST_ANY_RE = re.compile("|".join(f"(?:{p})" for p in PEST_PATTERNS.values()), re.IGNORECASE)
PEST_FREE_RE = re.compile(r"\b(?:pest|disease)[- ](?:free|resistant)\b|\bno (?:serious |significant )?(?:insect |pest |disease )?(?:pests?|diseases?|problems?)\b",
                          re.IGNORECASE)

# any sentence about pests or diseases, also of the ones not in PEST_PATTERNS:
# "Watch for leafhoppers", "Beech scale can be a problem", "infested by ..."
PEST_CONTEXT_RE = re.compile(
    r"\b(?:pests?|diseases?|diseased|fung(?:us|i|al)|infect\w*|infest\w*|pathogens?|pathogenic|"
    r"parasit\w*|insects?|larvae|grubs?|virus(?:es)?|viral|bacteri\w*|blights?|rots?|cankers?|"
    r"mildews?|galls?|watch (?:out )?for|keep an eye (?:out )?for|"
    r"(?:attacked|infested|defoliated|browsed) by)\b",
    re.IGNORECASE)


def find_terms(text: str, patterns: dict[str, re.Pattern]) -> tuple[list[str], dict[str, list[str]]]:
    """Canonical names whose pattern occurs in the text, with up to
    MAX_EVIDENCE sentences per name as evidence."""
    evidence: dict[str, list[str]] = {}
    for sentence in sentences(text):
        for name, regex in patterns.items():
            if regex.search(sentence):
                found = evidence.setdefault(name, [])
                if len(found) < MAX_EVIDENCE:
                    found.append(sentence[:MAX_EVIDENCE_CHARS])
    return sorted(evidence), evidence


def pest_sentences(text: str) -> list[str]:
    """Every sentence about pests or diseases: the pest:<word> query must find
    any pest, not only the canonical ones of PEST_PATTERNS."""
    found = [s[:MAX_EVIDENCE_CHARS] for s in sentences(text)
             if PEST_CONTEXT_RE.search(s) or PEST_ANY_RE.search(s)]
    return list(dict.fromkeys(found))[:MAX_PEST_SENTENCES]


def habitat_sentences(text: str, limit: int) -> list[str]:
    """Sentences that say where the plant grows in the wild; sentences about
    gardens and cultivation ("planted in the woodland garden") are left out
    unless they say "native of"."""
    found = [s[:MAX_EVIDENCE_CHARS * 2] for s in sentences(text)
             if HABITAT_SENTENCE_RE.search(s)
             and (not HABITAT_SKIP_RE.search(s) or NATIVE_OF_RE.search(s))]
    return list(dict.fromkeys(found))[:limit]


# ---------------------------------------------------------------------------
# Synonyms
# ---------------------------------------------------------------------------
# misapplied names in a synonym list: "Potentilla nepalensis D.Don, not Hook."
# is a different plant than Potentilla nepalensis Hook. of the gardens
MISAPPLIED_RE = re.compile(r",? not\b|\bnon\b|\bauct\.|\bsensu\b|\bof (?:many|some) authors\b|\bmisapplied\b")


def clean_sci_name(name: str) -> str:
    """'Picea excelsa (Lam.) Peterm.' -> 'Picea excelsa'; the rank (var., subsp.)
    and a cultivar in quotes are kept, the authors are dropped."""
    name = one_line(htmllib.unescape(name or ""))
    m = SCI_NAME_RE.match(name)
    if not m:
        return ""
    result = " ".join(m.group(0).split())
    cultivar = CULTIVAR_RE.search(name[m.end():])
    if cultivar:
        result += f" '{cultivar.group(1).strip()}'"
    return result


def synonym_names(raw: list[str]) -> list[str]:
    names = (clean_sci_name(s) for s in raw if not MISAPPLIED_RE.search(s))
    return list(dict.fromkeys(n for n in names if n))


# ---------------------------------------------------------------------------
# Trees and Shrubs Online
# ---------------------------------------------------------------------------
TSO_TITLE_RE = re.compile(r"<title>(.*?) - Trees and Shrubs Online</title>", re.DOTALL)
# right column: <h3>Family</h3><ul class='uk-list ids-list-small'><li>Pinaceae</ul>
TSO_LIST_RE = re.compile(
    r"<h3[^>]*>\s*(Family|Genus|Common Names|Synonyms|Infraspecifics|Species in genus)\s*</h3>"
    r"\s*<ul[^>]*>(.*?)</ul>",
    re.DOTALL,
)
LI_RE = re.compile(r"<li\b[^>]*>(.*?)(?=<li\b|</li>|$)", re.DOTALL)
TSO_GENUS_LINK_RE = re.compile(r"<a href=['\"]?(/articles/[^/'\" >]+/)")
# editorial note, a box inside the summary block: <div uk-alert><h3>Editorial Note</h3><p>...</div>
# it is cut out first, else its </div> would end the summary block too early
TSO_ALERT_RE = re.compile(r"<div uk-alert>(?:\s*<h3>[^<]*</h3>)?(.*?)</div>", re.DOTALL)
# summary block: description, then <p><b>Distribution&ensp;</b>... fields
TSO_SUMMARY_RE = re.compile(r"<div class=uk-text-small>(.*?)</div>", re.DOTALL)
TSO_FIELD_RE = re.compile(r"<p><b>([^<]{2,40}?)&ensp;</b>(.*?)(?=<p>|$)", re.DOTALL)
TSO_COUNTRY_RE = re.compile(r"<span style=font-variant:small-caps;>([^<]+)</span>")
TSO_MAIN_RE = re.compile(r"<div class=tso-main-text>(.*?)</div>", re.DOTALL)
# infraspecific taxa and cultivars below the main text:
# <hr/><h3 id=10731>'Acrocona'</h3> ... text ... <hr/><h3 id=...
TSO_SECTION_RE = re.compile(
    r"<hr/><h3 id=(\d+)>(.*?)</h3>(.*?)(?=<hr/><h3 id=|<div class=\"uk-section|$)", re.DOTALL)
# photo captions of the image galleries inside the cultivar sections
TSO_GALLERY_RE = re.compile(r"<div class=\"uk-card-footer[^\"]*tso-caption\">.*?</div>", re.DOTALL)
# other names of a cultivar: <b>Synonyms&thinsp;/&thinsp;alternative names</b><br/>
#   <i>Picea abies </i>'Glauca Pendula'<br/></div>
TSO_SECTION_SYNONYMS_RE = re.compile(
    r"<b>Synonyms&thinsp;/&thinsp;alternative names</b><br/>(.*?)(?=<p\b|</div>)", re.DOTALL)
BR_RE = re.compile(r"<br\s*/?>")
TSO_CREDITS_RE = re.compile(r"<h2>Credits</h2>\s*<p>(.*?)(?=<p>|</div>)", re.DOTALL)
CONSERVATION_RE = re.compile(r"\((LC|NT|VU|EN|CR|EW|EX|DD|NE)\)")
RHS_RE = re.compile(r"\b(H[1-7][a-c]?)\b")

TSO_FIELD_NAMES = {
    "Distribution": "distribution",
    "Habitat": "habitat",
    "USDA Hardiness Zone": "usda_zone",
    "RHS Hardiness Rating": "rhs_rating",
    "Conservation status": "conservation_status",
    "Awards": "awards",
    "Taxonomic note": "taxonomic_note",
}


def tso_lists(page: str) -> dict[str, list[str]]:
    lists = {}
    for title, items in TSO_LIST_RE.findall(page):
        if title not in lists:      # the mobile copy of the column repeats them
            lists[title] = [one_line(clean(li)) for li in LI_RE.findall(items) if clean(li)]
    return lists


def extract_tso(page: str, url: str) -> dict:
    segments = [s for s in urlparse(url).path.split("/") if s]
    kind = "species" if len(segments) >= 3 else "genus"
    title = one_line(clean(first(TSO_TITLE_RE, page) or ""))
    lists = tso_lists(page)

    genus = None
    if kind == "species" and lists.get("Genus"):
        genus = lists["Genus"][0]
    elif kind == "genus":
        genus = title

    record = {
        "source": "tso",
        "kind": kind,
        "url": url,
        "slug": segments[-1] if segments else "",
        "genus_slug": segments[1] if len(segments) > 1 else "",
        "title": title,
        "name": parse_sci_name(title),
        "family": (lists.get("Family") or [None])[0],
        "genus": genus,
        "common_names": lists.get("Common Names", []),
        "synonyms": lists.get("Synonyms", []),
        "synonym_names": synonym_names(lists.get("Synonyms", [])),
        "infraspecifics": lists.get("Infraspecifics", []),
        "species_in_genus": lists.get("Species in genus", []),
        "description": "",
        "main_text": "",
        "sections": [],
        "credits": one_line(clean(first(TSO_CREDITS_RE, page) or "")),
    }
    for key in TSO_FIELD_NAMES.values():
        record[key] = ""

    record["editorial_note"] = one_line(clean(" ".join(TSO_ALERT_RE.findall(page))))
    summary = first(TSO_SUMMARY_RE, TSO_ALERT_RE.sub("", page)) or ""
    if summary:
        description_html = summary.split("<p><b>", 1)[0]
        record["description"] = clean(description_html)
        for label, value in TSO_FIELD_RE.findall(summary):
            key = TSO_FIELD_NAMES.get(label.strip())
            if key:
                record[key] = one_line(clean(value))
                if key == "distribution":
                    record["countries"] = [one_line(c) for c in TSO_COUNTRY_RE.findall(value)]
    record.setdefault("countries", [])

    record["main_text"] = clean(first(TSO_MAIN_RE, page) or "")
    for anchor, name, body in TSO_SECTION_RE.findall(page):
        other_names = first(TSO_SECTION_SYNONYMS_RE, body) or ""
        record["sections"].append({
            "id": anchor,
            "name": one_line(clean(name)),
            "synonyms": [one_line(clean(n)) for n in BR_RE.split(other_names) if clean(n)],
            "text": clean(TSO_GALLERY_RE.sub(" ", body))[:4000],
        })

    # derived values
    record["usda"] = parse_zones(record["usda_zone"])
    record["rhs"] = first(RHS_RE, record["rhs_rating"])
    record["conservation"] = first(CONSERVATION_RE, record["conservation_status"])
    # the older articles have no description block; their text starts with it
    first_sentence = (sentences(record["description"]) or sentences(record["main_text"]) or [""])[0]
    record["height"] = parse_height(first_sentence)
    record["life_form"] = sorted({m.lower() for m in LIFE_FORM_RE.findall(first_sentence)})
    record["leaf_habit"] = sorted({m.lower() for m in LEAF_HABIT_RE.findall(
        record["description"] + " " + record["main_text"][:1500])})

    # the sentences of the article that describe where the plant grows in the
    # wild; for the older (Bean) articles without a Habitat field the only source
    record["habitat_from_text"] = " ".join(habitat_sentences(record["main_text"], MAX_HABITAT_SENTENCES))
    habitat_text = record["habitat"] or record["habitat_from_text"]
    record["altitude"] = parse_altitude(habitat_text)
    record["mountain_terms"] = sorted({m.lower() for m in MOUNTAIN_RE.findall(habitat_text)})
    record["mountain"] = bool(record["mountain_terms"]) or bool(
        record["altitude"] and record["altitude"]["max_m"] >= MOUNTAIN_MIN_ALTITUDE)

    all_text = "\n".join([record["description"], record["main_text"]]
                         + [s["text"] for s in record["sections"]])
    record["pests"], record["pest_evidence"] = find_terms(all_text, PEST_RES)
    record["pest_sentences"] = pest_sentences(all_text)
    return record


# ---------------------------------------------------------------------------
# gardenia.net
# ---------------------------------------------------------------------------
GARDENIA_TITLE_RE = re.compile(r"<h1 class=\"h3\">(.*?)</h1>", re.DOTALL)
# common names under the title: <p class="h5"><em> Norway Spruce, European Spruce </em></p>
GARDENIA_COMMON_RE = re.compile(r"</h1>\s*<p class=\"h5\"><em>(.*?)</em></p>", re.DOTALL)
# description: from the text block to the buttons below it
GARDENIA_TEXT_RE = re.compile(
    r"<div class=\"single-section__main-text\">(.*?)<!--Main text button-->", re.DOTALL)
GARDENIA_BULLET_RE = re.compile(r"<li>(.*?)</li>", re.DOTALL)
# "Requirements" table; the page has a mobile and a desktop copy, the first is used
GARDENIA_TABLE_RE = re.compile(
    r"<table class=\"right-information-block\">(.*?)</table>", re.DOTALL)
GARDENIA_ROW_RE = re.compile(r"<th>\s*(.*?)\s*</th>\s*<td>\s*(.*?)\s*</td>", re.DOTALL)
# "Picea abies (Norway Spruce)" -> name and the common name in brackets
TITLE_SPLIT_RE = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")
# metric part of the Height / Spread cell: "40' - 60' (12.2m - 18.3m)",
# "1' - 2' (30cm - 60cm)", "3' - 5' (90cm - 1.5m)", "6\" (15cm)"
METRIC_RE = re.compile(r"\((\d+(?:\.\d+)?)\s*(cm|m)(?:\s*-\s*(\d+(?:\.\d+)?)\s*(cm|m))?\)")
# "native to Europe.", "Native to eastern Asia, particularly Japan and China, it has ..."
# "Native to Central and Southern Europe, Fagus sylvatica (European Beech) is ..."
NATIVE_RE = re.compile(
    r"\b[Nn]ative (?:to|of|in) (.{3,150}?)"
    r"(?=[.;:(]|,\s*(?:it|this|these|they|its|where|which|the plant)\b"
    r"|,\s*[A-Z][a-z]+ [a-z]{3,}(?: [‘'(]| is\b| are\b)|\s(?:and|but) (?:is|are|it)\b|$)")
AWARD_RE = re.compile(r"\bAward of Garden Merit\b|\bAGM\b")
# scientific names hidden among the common names: "Liverleaf, …, Anemone hepatica,
# Hepatica triloba", "Pecan, …, Carya pecan, Juglans illinoensis"
GARDENIA_SYNONYM_RE = re.compile(
    r"^(?:[×x]\s?)?(?P<genus>[A-Z][a-zë]+)(?: [×x])? (?P<epithet>[a-zë][a-zë-]{2,})"
    r"(?: (?:var\.|subsp\.|ssp\.|f\.) [a-zë-]+)?(?: ['‘’\"].+['’\"])?$")
# lower-case English words of common names that look like an epithet:
# "Cashew tree", "Macadamia nut", "Cavendish banana"
COMMON_WORDS = set("""
tree trees nut nuts plant plants shrub bush vine fruit berry berries lily fern palm grass flower
flowers rose orange lime lemon apple pear plum cherry banana plantain pine oak fir spruce maple
ash elm willow bamboo tea coffee pepper bean pea fig kiwi mallow daisy violet sage mint thyme
""".split())
# endings of Latin epithets; a candidate of another genus must have one ("Juglans
# illinoensis"), so that "Sweet pecan" stays a common name
LATIN_ENDING_RE = re.compile(r"(?:a|ae|i|us|um|is|es|e|ens|ans|ax|ex|ix|or|on|os|as|ys)$")


def split_scientific(names: list[str], genus: str | None) -> tuple[list[str], list[str]]:
    """Common names list -> (common names, scientific synonyms)."""
    common, scientific = [], []
    for name in names:
        m = GARDENIA_SYNONYM_RE.match(name)
        is_scientific = bool(m) and m.group("epithet") not in COMMON_WORDS and (
            m.group("genus").lower() == genus or LATIN_ENDING_RE.search(m.group("epithet")))
        (scientific if is_scientific else common).append(name)
    return common, scientific


GARDENIA_FIELD_NAMES = {
    "Hardiness": "hardiness",
    "Heat Zones": "heat_zones",
    "Climate Zones": "climate_zones",
    "Plant Type": "plant_type",
    "Plant Family": "family",
    "Genus": "genus",
    "Common names": "common_names_table",
    "Exposure": "exposure",
    "Season of Interest": "season_of_interest",
    "Height": "height_raw",
    "Spread": "spread_raw",
    "Spacing": "spacing",
    "Maintenance": "maintenance",
    "Water Needs": "water_needs",
    "Soil Type": "soil_type",
    "Soil pH": "soil_ph",
    "Soil Drainage": "soil_drainage",
    "Characteristics": "characteristics",
    "Tolerances": "tolerances",
    "Attracts": "attracts",
    "Garden Uses": "garden_uses",
    "Garden Styles": "garden_styles",
    "Toxic to Humans": "toxic_humans",
    "Toxic to Cats": "toxic_cats",
    "Toxic to Dogs": "toxic_dogs",
    "Toxic to Horses": "toxic_horses",
}
# table cells that hold a list of values
GARDENIA_LIST_FIELDS = {"plant_type", "exposure", "soil_type", "soil_ph", "soil_drainage",
                        "characteristics", "tolerances", "attracts", "garden_uses",
                        "garden_styles", "common_names_table"}


def split_list(value: str) -> list[str]:
    return [v.strip() for v in re.split(r",\s*", value) if v.strip()]


def parse_metric_range(raw: str) -> dict | None:
    """"40' - 60' (12.2m - 18.3m)" -> {'min_m': 12.2, 'max_m': 18.3}"""
    m = METRIC_RE.search(raw or "")
    if not m:
        return None
    low = float(m.group(1)) * (0.01 if m.group(2) == "cm" else 1.0)
    high = float(m.group(3)) * (0.01 if m.group(4) == "cm" else 1.0) if m.group(3) else low
    return {"min_m": round(low, 2), "max_m": round(high, 2)}


def extract_gardenia(page: str, url: str) -> dict:
    title = one_line(clean(first(GARDENIA_TITLE_RE, page) or ""))
    split = TITLE_SPLIT_RE.match(title)
    sci_name = split.group(1) if split else title
    title_common = split.group(2) if split else ""

    common = one_line(clean(first(GARDENIA_COMMON_RE, page) or ""))
    text_html = first(GARDENIA_TEXT_RE, page) or ""
    bullets = [one_line(clean(b)) for b in GARDENIA_BULLET_RE.findall(text_html)]
    text = clean(text_html)

    name = parse_sci_name(sci_name)
    common_names, scientific = split_scientific(
        split_list(common) or ([title_common] if title_common else []), name.get("genus"))
    record = {
        "source": "gardenia",
        "kind": "plant",
        "url": url,
        "slug": urlparse(url).path.rstrip("/").rsplit("/", 1)[-1],
        "title": title,
        "scientific_name": sci_name,
        "name": name,
        "common_names": common_names,
        "scientific_synonyms": scientific,
        "description": text,
        "bullets": [b for b in bullets if b],
    }
    for key in GARDENIA_FIELD_NAMES.values():
        record[key] = [] if key in GARDENIA_LIST_FIELDS else ""

    table = first(GARDENIA_TABLE_RE, page) or ""
    for label, value in GARDENIA_ROW_RE.findall(table):
        key = GARDENIA_FIELD_NAMES.get(one_line(clean(label)))
        if not key:
            continue
        value = one_line(clean(value)).replace("What's My Zone?", "").strip()
        record[key] = split_list(value) if key in GARDENIA_LIST_FIELDS else value

    record["usda"] = parse_zones(record["hardiness"])
    record["height"] = parse_metric_range(record["height_raw"])
    record["spread"] = parse_metric_range(record["spread_raw"])
    record["native_to"] = one_line(first(NATIVE_RE, text) or "")
    record["award_agm"] = bool(AWARD_RE.search(text))

    record["pest_sentences"] = pest_sentences(text)
    pest_text = "\n".join(record["pest_sentences"])
    record["pests"], record["pest_evidence"] = find_terms(pest_text, PEST_RES)
    record["pest_free"] = bool(PEST_FREE_RE.search(pest_text))
    record["habitat_sentences"] = habitat_sentences(text, 5)
    return record


# ---------------------------------------------------------------------------
# Batch run
# ---------------------------------------------------------------------------
def read_page(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _extract_item(item: tuple[str, str, str]) -> dict | None:
    site, url, path = item
    try:
        page = read_page(path)
    except OSError:
        return None
    record = extract_tso(page, url) if site == "tso" else extract_gardenia(page, url)
    record["file"] = path
    return record


def manifest_items(site: str) -> list[tuple[str, str, str]]:
    path = TSO_MANIFEST if site == "tso" else GARDENIA_MANIFEST
    items = json.loads(path.read_text(encoding="utf-8"))
    if site == "gardenia":
        items = [i for i in items if i.get("kind") == "plant"]
    return [(site, i["url"], i["saved_as"]) for i in items]


def run(site: str, workers: int):
    DATA_DIR.mkdir(exist_ok=True)
    out = TSO_OUT if site == "tso" else GARDENIA_OUT
    items = manifest_items(site)
    started = time.time()
    written = 0
    with Pool(workers) as pool, out.open("w", encoding="utf-8") as f:
        for n, record in enumerate(pool.imap(_extract_item, items, chunksize=16), 1):
            if record is not None:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
            if n % 1000 == 0:
                print(f"  {site}: {n}/{len(items)} pages ({time.time() - started:.0f} s)")
    print(f"{site}: {written} records -> {out} ({time.time() - started:.0f} s)")


def show(path: str):
    page = read_page(path)
    if "gardenia" in Path(path).parts:
        url = "https://www.gardenia.net/" + Path(path).stem.replace("_", "/", 1)
        record = extract_gardenia(page, url)
    else:
        url = "https://www.treesandshrubsonline.org/" + Path(path).stem.replace("_", "/") + "/"
        record = extract_tso(page, url)
    print(json.dumps(record, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="REGEX extractor for TSO and gardenia pages")
    parser.add_argument("--site", choices=["tso", "gardenia", "all"], default="all")
    parser.add_argument("--workers", type=int, default=4, help="parallel processes")
    parser.add_argument("--show", metavar="HTML_FILE", help="print the record of one page")
    args = parser.parse_args()

    if args.show:
        sys.stdout.reconfigure(encoding="utf-8")
        show(args.show)
    else:
        for name in (["tso", "gardenia"] if args.site == "all" else [args.site]):
            run(name, args.workers)
