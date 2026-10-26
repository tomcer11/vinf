"""
Extraction of Trees and Shrubs Online pages (crawled_pages/tso/pages/articles_*.html), REGEX only.

A species page has three parts that matter:
  <h1><i>Fagus sylvatica</i> <span class=authors>L.</span></h1>
  right column     <h3>Family</h3><ul class='uk-list ids-list-small'><li>Fagaceae</ul>
                   ... Genus, Common Names, Synonyms, Infraspecifics
  <div class=uk-text-small>
                   may start with an editorial note <div uk-alert> (dropped)
                   newer articles: the description paragraph ("Tree to 50 m ...
                   Leaves ... Flowers ...") followed by labelled blocks
                   <b>Distribution&ensp;</b> ... <b>Habitat&ensp;</b> ...
                   <b>USDA Hardiness Zone&ensp;</b>4 ... (some pages write the
                   labels inline: "... 2008. <b>Distribution</b> CHINA: ...")
                   older articles (Bean's book): empty, or only the labels
  <div class=tso-main-text>
                   the article; when there is no description before the labels,
                   its first paragraph is the description ("A deciduous tree ...
                   Leaves ... Fruits ...")

A genus page has the description of the genus in <div class=uk-text-small>,
or in older articles in the first paragraph of <div class=tso-main-text>.
"""

import re

from extractor.tree import clean_html, latin_part, short_value

TEXT_SMALL_START = "<div class=uk-text-small>"
MAIN_TEXT_START = "<div class=tso-main-text>"

H1_RE = re.compile(r"<h1>(.*?)</h1>", re.DOTALL)
AUTHORS_RE = re.compile(r"<span class=authors>(.*?)</span>", re.DOTALL)
SIDEBAR_RE = re.compile(
    r"<h3[^>]*>([^<]+)</h3>\s*<ul class='uk-list ids-list-small'>(.*?)</ul>",
    re.DOTALL,
)
LI_SPLIT_RE = re.compile(r"<li[^>]*>")
# Paragraph boundaries of the minified HTML: <p ...> (rarely closed) or <br><br>
PARAGRAPH_SPLIT_RE = re.compile(r"<p(?:\s[^>]*)?>|</p>|<br\s*/?>\s*<br\s*/?>")
# "Editorial Note" box of revised articles ("Bean treated this species under ...")
ALERT_RE = re.compile(r"<div uk-alert>.*?</div>", re.DOTALL)
# Image galleries keep their captions in attributes: data-caption="<p>...</p>"
CAPTION_ATTR_RE = re.compile(r'\sdata-(?:caption|alt)="[^"]*"')
BOLD_RE = re.compile(r"<b>([^<]{2,40}?)(?:&ensp;|\s)*</b>")
CODE_RE = re.compile(r"\(([A-Z]{2})\)")

# Labels of the blocks in <div class=uk-text-small>, compared without spaces and
# case ("USDA Hardi ness Zone" occurs once). Only some of them are kept, the
# others just end the previous block.
BLOCK_LABELS = {
    "distribution": "distribution",
    "habitat": "habitat",
    "usdahardinesszone": "usda",
    "rhshardinessrating": "rhs",
    "rhshardiness": "rhs",
    "conservationstatus": "conservation",
    "taxonomicnote": None,
    "awards": None,
    "illustration": None,
    "cross-reference": None,
    "cross-references": None,
    "season": None,
}

# IUCN categories written out without the code, longest phrases first
CONSERVATION_CODES = [
    ("critically endangered", "cr"),
    ("extinct in the wild", "ew"),
    ("near threatened", "nt"),
    ("not evaluated", "ne"),
    ("least concern", "lc"),
    ("data deficient", "dd"),
    ("lower risk", "lr"),
    ("endangered", "en"),
    ("vulnerable", "vu"),
    ("extinct", "ex"),
]


def sidebar_lists(html: str) -> dict[str, list[str]]:
    """The lists of the right column, by heading. The first list of each
    heading wins (Infraspecifics appears twice: desktop and mobile layout)."""
    lists = {}
    for match in SIDEBAR_RE.finditer(html):
        heading = clean_html(match.group(1))
        if heading in lists:
            continue
        items = [clean_html(item) for item in LI_SPLIT_RE.split(match.group(2))]
        lists[heading] = [item for item in items if item]
    return lists


def paragraphs(fragment: str) -> list[str]:
    """Non-empty cleaned paragraphs of an HTML fragment."""
    fragment = CAPTION_ATTR_RE.sub("", fragment)
    parts = (clean_html(part) for part in PARAGRAPH_SPLIT_RE.split(fragment))
    return [part for part in parts if part]


def text_small_block(html: str) -> str:
    """Raw HTML of <div class=uk-text-small> without its editorial note, ''
    if the page has none. The block reaches up to <div class=tso-main-text>,
    because the note is a nested <div uk-alert> whose </div> comes first."""
    start = html.find(TEXT_SMALL_START)
    if start < 0:
        return ""
    start += len(TEXT_SMALL_START)
    end = html.find(MAIN_TEXT_START, start)
    return ALERT_RE.sub("", html[start:end if end >= 0 else len(html)])


def split_blocks(block: str) -> tuple[str, dict[str, str]]:
    """(HTML before the first label, {block name: HTML of the block})."""
    marks = []
    for match in BOLD_RE.finditer(block):
        label = match.group(1).replace(" ", "").lower()
        if label in BLOCK_LABELS:
            marks.append((match, BLOCK_LABELS[label]))

    if not marks:
        return block, {}
    blocks = {}
    for n, (match, name) in enumerate(marks):
        end = marks[n + 1][0].start() if n + 1 < len(marks) else len(block)
        if name and name not in blocks:
            blocks[name] = block[match.end():end]
    return block[:marks[0][0].start()], blocks


def conservation_value(text: str) -> str:
    """'Least concern (LC)' -> 'conservation:lc', 'Lower Risk.' -> 'conservation:lr'."""
    code = CODE_RE.search(text)
    if code:
        return short_value("conservation", code.group(1))
    lower = text.lower()
    for phrase, code in CONSERVATION_CODES:
        if lower.startswith(phrase):
            return short_value("conservation", code)
    return ""


def expand_genus(name: str, genus: str) -> str:
    """'Q. pedunculata' -> 'Quercus pedunculata' when the genus is Quercus."""
    first, _, rest = name.partition(" ")
    if genus and rest and first == genus[0] + ".":
        return f"{genus} {rest}"
    return name


def first_main_paragraph(html: str) -> str:
    start = html.find(MAIN_TEXT_START)
    if start < 0:
        return ""
    found = paragraphs(html[start + len(MAIN_TEXT_START):start + 50000])
    return found[0] if found else ""


def parse_tso_species(html: str) -> dict:
    """Fields of a Tree from one TSO species page (keys as in tree.Tree)."""
    out = {}

    h1 = H1_RE.search(html)
    if h1:
        authors = AUTHORS_RE.search(h1.group(1))
        out["tso_authors"] = clean_html(authors.group(1)) if authors else ""
        out["name"] = clean_html(AUTHORS_RE.sub("", h1.group(1)))

    lists = sidebar_lists(html)
    out["family"] = (lists.get("Family") or [""])[0]
    out["genus"] = (lists.get("Genus") or [""])[0]
    out["common_names"] = lists.get("Common Names", [])
    out["synonyms"] = [expand_genus(latin_part(s), out["genus"]) for s in lists.get("Synonyms", [])]
    out["cultivars"] = [c.strip("'‘’ ") for c in lists.get("Infraspecifics", [])]

    # Without a description before the labels (all older articles, and newer
    # ones that only added labels to Bean's text) the article starts with it.
    before, blocks = split_blocks(text_small_block(html))
    out["tso_description"] = "\n".join(paragraphs(before)) or first_main_paragraph(html)

    out["tso_distribution"] = clean_html(blocks.get("distribution", ""))
    out["tso_habitat"] = clean_html(blocks.get("habitat", ""))
    out["tso_hardiness"] = short_value("hardiness", clean_html(blocks.get("usda", "")).rstrip("."))
    out["tso_rhs"] = short_value("rhs", clean_html(blocks.get("rhs", "")).rstrip("."))
    out["tso_conservation"] = conservation_value(clean_html(blocks.get("conservation", "")))
    return out


def parse_tso_genus(html: str) -> str:
    """Description of the genus from a TSO genus page (older articles: the
    first paragraph of the article, "A genus of shrubs and small trees ...")."""
    before, _ = split_blocks(text_small_block(html))
    return "\n".join(paragraphs(before)) or first_main_paragraph(html)
