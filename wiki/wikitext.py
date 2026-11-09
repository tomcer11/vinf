"""
Wikitext of one Wikipedia article -> the attributes joined to a Tree, REGEX only.

A taxon article looks like this (Kalmia latifolia, shortened):

  {{Short description|Species of plant}}
  {{Speciesbox
  | status = LC
  | status_system = IUCN3.1
  | status_ref = <ref>{{cite iucn |author=Stritch, L. |date=2018 ...}}</ref>
  | genus = Kalmia
  | species = latifolia
  | authority = [[Carl Linnaeus|L.]]
  | synonyms = {{Species list |Kalmia lucida |Raf. |...}}
  }}
  '''''Kalmia latifolia''''', the '''mountain laurel''', '''calico-bush''' ... is a
  [[flowering plant]] ... native to the [[eastern United States]].
  == Description ==
  ...
  == Distribution and habitat ==
  ...
  [[Category:Trees of Northern America]]

Templates {{...}} nest, and one regex cannot match nested braces. The text is
therefore cleaned from the inside out: the innermost template (one without
braces inside) is replaced by its text, again and again until none is left.
The taxobox itself is cut out by counting {{ and }} tokens found by a regex.

Other taxoboxes: {{Automatic taxobox | taxon = Acer}} (genera and higher),
{{Infraspeciesbox | genus | species | subspecies / varietas / forma}},
{{Subspeciesbox}}, {{Hybridbox}}.
"""

import html as htmllib
import re

from extractor.tree import latin_part, name_key

# --- removed before anything else -------------------------------------------
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# <ref name=x/>, <ref name="x">...</ref>, also <references/>
REF_RE = re.compile(r"<ref[^>]*?/>|<ref(?:\s[^>]*)?>.*?</ref>", re.DOTALL | re.IGNORECASE)
BLOCK_TAGS_RE = re.compile(
    r"<(gallery|math|syntaxhighlight|timeline|imagemap|score|chem|graph)\b.*?</\1>", re.DOTALL | re.IGNORECASE)

# --- templates ----------------------------------------------------------------
INNER_TEMPLATE_RE = re.compile(r"\{\{([^{}]*)\}\}")
# a pipe that is not inside a [[link|text]]
ARG_SPLIT_RE = re.compile(r"\|(?![^\[\]]*\]\])")
NAMED_ARG_RE = re.compile(r"^\s*[\w -]+?\s*=(.*)$", re.DOTALL)
TAXOBOX_START_RE = re.compile(
    r"\{\{\s*(speciesbox|taxobox|automatic[ _]taxobox|subspeciesbox|infraspeciesbox|hybridbox)\s*(?=[|}\n])",
    re.IGNORECASE)
BRACE_TOKEN_RE = re.compile(r"\{\{|\}\}|\[\[|\]\]|\|")

# templates replaced by their last / first positional argument, or by a constant
LAST_ARG = {"nowrap", "nobr", "small", "smaller", "big", "nobold", "noitalic", "em", "var", "lang",
            "langx", "transl", "transliteration", "sic", "lang-la", "vernacular"}
FIRST_ARG = {"taxlink", "ill", "au", "small caps", "sc", "abbr", "visible anchor", "nihongo",
             "anchor text", "linktext", "botanist", "auth"}
CONSTANT = {"snd": " – ", "spaced ndash": " – ", "ndash": "–", "mdash": "—", "nbsp": " ",
            "'": "'", "=": "=", "!": "|", "-": "", "clear": "", "•": " • "}
LIST_TEMPLATES = {"unbulleted list", "ubl", "plainlist", "flatlist", "hlist", "bulleted list", "collapsible list"}
RANGE_WORDS = {"-", "–", "to", "and", "or", "x", "×", "by", "and(-)", "to(-)"}

# --- links and the rest of the markup --------------------------------------------
INNER_LINK_RE = re.compile(r"\[\[([^\[\]]*)\]\]")
DROPPED_LINK_RE = re.compile(r"^\s*(?:file|image|media|category|[a-z]{2,3}(?:-[a-z]+)?)\s*:", re.IGNORECASE)
EXTERNAL_LINK_RE = re.compile(r"\[(?:https?:)?//[^\s\]]+(?:\s+([^\]]*))?\]")
TABLE_RE = re.compile(r"^\s*\{\|.*?^\s*\|\}", re.DOTALL | re.MULTILINE)
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
QUOTES_RE = re.compile(r"'{2,}")
HEADING_LINE_RE = re.compile(r"^=+.*?=+\s*$", re.MULTILINE)
LIST_MARK_RE = re.compile(r"^[*#:;]+\s*", re.MULTILINE)
MAGIC_WORD_RE = re.compile(r"__[A-Z]+__")
SPACE_RE = re.compile(r"[ \t ]+")

# --- article structure ---------------------------------------------------------
SECTION_RE = re.compile(r"^==\s*([^=].*?)\s*==\s*$", re.MULTILINE)
CATEGORY_RE = re.compile(r"\[\[\s*Category\s*:\s*([^\]|]+)", re.IGNORECASE)
# zero-width, so overlapping matches are found too: in "'''a''', or '''b'''" the
# match ", or " must not consume the ''' in front of b
BOLD_RE = re.compile(r"(?='''([^']+?)''')")
BETWEEN_BOLD_RE = re.compile(r"[\s,.;:()]")
TITLE_DISAMBIGUATION_RE = re.compile(r"\s*\([^()]*\)$")
PARENTHESES_RE = re.compile(r"\s*\([^()]*\)")
HYBRID_SIGN_RE = re.compile(r"×(?=\w)")
IUCN_STATUS_RE = re.compile(r"^([a-z]{2})(?:/[a-z]{2})?$")
MAX_NAME_WORDS = 6

# level-2 section heading -> attribute; the first matching attribute wins
SECTION_ATTRIBUTES = [
    ("description", re.compile(r"descript|morpholog|characteristic|appearance|identification|botany", re.I)),
    ("distribution", re.compile(r"distribut|habitat|\brange\b", re.I)),
    ("ecology", re.compile(r"ecolog", re.I)),
    ("uses", re.compile(r"\buses?\b|cultivat|\bwood\b|timber|culinary|\bfood\b|medic|toxic|horticult", re.I)),
]
INFRA_RANKS = (("subspecies", "subsp."), ("varietas", "var."), ("variety", "var."), ("forma", "f."))


# === cleaning ===================================================================

def strip_refs_and_comments(text: str) -> str:
    return REF_RE.sub("", COMMENT_RE.sub("", text))


def template_args(inner: str) -> tuple[str, list[str], dict[str, str]]:
    """'convert|20|m|ft|abbr=on' -> ('convert', ['20', 'm', 'ft'], {'abbr': 'on'})."""
    parts = ARG_SPLIT_RE.split(inner)
    name = parts[0].strip().lower().replace("_", " ")
    positional, named = [], {}
    for part in parts[1:]:
        match = NAMED_ARG_RE.match(part)
        if match:
            named[part.split("=", 1)[0].strip().lower()] = match.group(1).strip()
        else:
            positional.append(part.strip())
    return name, positional, named


def render_template(inner: str) -> str:
    """Text of one template without nested templates; '' for templates that
    carry no prose (citations, hatnotes, infoboxes, maps ...)."""
    name, args, _ = template_args(inner)
    if name in CONSTANT:
        return CONSTANT[name]
    if name in ("convert", "cvt") and args:
        # {{convert|20|–|30|m|ft}} -> '20–30 m', {{convert|10|m|ft}} -> '10 m'
        if len(args) >= 4 and args[1] in RANGE_WORDS:
            sep = args[1] if args[1] in ("-", "–") else f" {args[1]} "
            return f"{args[0]}{sep}{args[2]} {args[3]}"
        return " ".join(args[:2])
    if name in ("circa", "c.") and args:
        return f"c. {args[0]}"
    if name == "frac" and args:
        return " ".join(args[:-2] + ["/".join(args[-2:])]) if len(args) >= 2 else args[0]
    if name == "species list":
        return "\n".join(args[0::2])
    if name in LIST_TEMPLATES:
        return "\n".join(args)
    if (name in LAST_ARG or name.startswith("lang-")) and args:
        return args[-1]
    if name in FIRST_ARG and args:
        return args[0]
    return ""


def render_templates(text: str) -> str:
    """Replace templates from the innermost ones out, until none is left."""
    for _ in range(50):
        replaced = INNER_TEMPLATE_RE.sub(lambda m: render_template(m.group(1)), text)
        if replaced == text:
            break
        text = replaced
    return text


def render_link(inner: str) -> str:
    """[[target|text]] -> text, [[target]] -> target, files and categories -> ''."""
    if DROPPED_LINK_RE.match(inner):
        return ""
    return inner.rsplit("|", 1)[-1]


def render_links(text: str) -> str:
    for _ in range(10):        # a file caption can hold links: [[File:x|thumb|A [[tree]]]]
        replaced = INNER_LINK_RE.sub(lambda m: render_link(m.group(1)), text)
        if replaced == text:
            break
        text = replaced
    return EXTERNAL_LINK_RE.sub(lambda m: m.group(1) or "", text)


def clean_wikitext(text: str) -> str:
    """Plain text of a piece of wikitext, one paragraph or list item per line."""
    text = BLOCK_TAGS_RE.sub("", strip_refs_and_comments(text))
    text = render_templates(text)
    text = TABLE_RE.sub("", text)
    text = render_links(text)
    text = BR_RE.sub("\n", text)
    text = TAG_RE.sub("", text)
    text = htmllib.unescape(text)
    text = QUOTES_RE.sub("", text)
    text = HEADING_LINE_RE.sub("", text)
    text = LIST_MARK_RE.sub("", text)
    text = MAGIC_WORD_RE.sub("", text)
    lines = (SPACE_RE.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


# === taxobox ====================================================================

def taxobox(text: str) -> tuple[str, dict[str, str]]:
    """(box name, {parameter: raw value}) of the first taxobox, ('', {}) if none.

    The box ends where the {{ ... }} depth returns to 0; parameters are split
    at the pipes that are not inside a nested template or link."""
    start = TAXOBOX_START_RE.search(text)
    if not start:
        return "", {}
    box = start.group(1).lower().replace("_", " ")
    depth, links, cut, params = 0, 0, None, []
    for token in BRACE_TOKEN_RE.finditer(text, start.start()):
        kind = token.group()
        if kind == "{{":
            depth += 1
        elif kind == "}}":
            depth -= 1
            if depth == 0:
                if cut is not None:
                    params.append(text[cut:token.start()])
                break
        elif kind == "[[":
            links += 1
        elif kind == "]]":
            links = max(0, links - 1)
        elif depth == 1 and links == 0:
            if cut is not None:
                params.append(text[cut:token.start()])
            cut = token.end()
    values = {}
    for param in params:
        name, sep, value = param.partition("=")
        if sep:
            values[name.strip().lower()] = value.strip()
    return box, values


def latin_name(params: dict[str, str]) -> str:
    """Latin name of the taxon: 'taxon', or genus + species (+ infraspecific rank)."""
    # 'genus = Sasa (plant)' names the genus article, the parentheses are not part of the name
    clean = lambda name: PARENTHESES_RE.sub("", clean_wikitext(params.get(name, "")).replace("\n", " ")).strip()
    if clean("taxon"):
        return clean("taxon")
    genus, species = clean("genus"), clean("species")
    if not (genus and species):
        return clean("binomial") or ""
    name = f"{genus} {species}"
    for param, rank in INFRA_RANKS:
        if clean(param):
            name += f" {rank} {clean(param)}"
    return name


def join_key(latin: str) -> str:
    """The key the join compares, the same for wiki and for tree names:
    extractor name_key ('×' for x, lower case), 'ssp.' as 'subsp.',
    '×acerifolia' as '× acerifolia'."""
    key = name_key(HYBRID_SIGN_RE.sub("× ", latin))
    return " ".join("subsp." if token == "ssp." else token for token in key.split())


def title_key(title: str) -> str:
    """'Magnolia (plant)' -> 'magnolia'."""
    return join_key(TITLE_DISAMBIGUATION_RE.sub("", title))


def synonym_names(value: str) -> list[str]:
    """Latin names from the synonyms parameter ({{Species list}}, a bullet
    list or <br> separated names), without their authors."""
    names = []
    for line in clean_wikitext(value).split("\n"):
        name = latin_part(line.strip(" ,;"))
        if len(name.split()) >= 2 and name not in names:
            names.append(name)
    return names


def conservation(params: dict[str, str]) -> str:
    """IUCN status as a short value like the TSO one: 'LC' -> 'conservation:lc',
    'LR/nt' (IUCN 2.3) -> 'conservation:lr'."""
    system = params.get("status_system", "").upper()
    status = clean_wikitext(params.get("status", "")).lower()
    match = IUCN_STATUS_RE.match(status)
    if "IUCN" in system and match:
        return f"conservation:{match.group(1)}"
    return ""


# === the whole article ============================================================

def lead_and_sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """(raw text before the first level-2 heading, [(heading, raw section text)])."""
    matches = list(SECTION_RE.finditer(text))
    lead = text[:matches[0].start()] if matches else text
    sections = []
    for n, match in enumerate(matches):
        end = matches[n + 1].start() if n + 1 < len(matches) else len(text)
        sections.append((match.group(1), text[match.end():end]))
    return lead, sections


def section_attributes(sections: list[tuple[str, str]]) -> dict[str, str]:
    """Cleaned text of the sections, merged per attribute (description, distribution, ecology, uses)."""
    found = {name: [] for name, _ in SECTION_ATTRIBUTES}
    for heading, body in sections:
        for name, pattern in SECTION_ATTRIBUTES:
            if pattern.search(heading):
                cleaned = clean_wikitext(body)
                if cleaned:
                    found[name].append(cleaned)
                break
    return {name: "\n".join(parts) for name, parts in found.items()}


def common_names(title: str, box_name: str, lead: str, latin: str) -> list[str]:
    """English names: the title when it is not the latin name ('Douglas fir'),
    the name on top of the taxobox and the bold names of the lead
    ('''mountain laurel'''), without the latin name itself."""
    names = []
    candidates = [TITLE_DISAMBIGUATION_RE.sub("", title), box_name]
    # "'''''Pseudotsuga menziesii'' var. ''glauca''''', or '''Rocky ...": the
    # text between two bold names (", or ") is matched too, it starts with punctuation
    candidates += [clean_wikitext(bold) for bold in BOLD_RE.findall(lead) if not BETWEEN_BOLD_RE.match(bold)]
    for name in candidates:
        name = name.replace("\n", " ").strip(" ,.:")
        # 'Ficus carica – Common fig' (the name on top of the box) contains the latin name
        if (name and len(name.split()) <= MAX_NAME_WORDS and not (latin and join_key(latin) in join_key(name))
                and name.lower() not in (n.lower() for n in names)):
            names.append(name)
    return names


def article_keys(title: str, text: str) -> dict:
    """Only the join keys of an article: much cheaper than parse_article,
    which runs only on the articles that were joined."""
    text = strip_refs_and_comments(htmllib.unescape(text))
    _, params = taxobox(text)
    latin = latin_name(params)
    return {
        "latin_key": join_key(latin),
        "title_key": title_key(title),
        "synonym_keys": [join_key(name) for name in synonym_names(params.get("synonyms", ""))],
    }


def parse_article(title: str, text: str) -> dict:
    """Attributes of one taxon article. `text` is the wikitext as stored in the
    dump (XML escaped)."""
    text = strip_refs_and_comments(htmllib.unescape(text))
    box, params = taxobox(text)
    latin = latin_name(params)
    lead, sections = lead_and_sections(text)
    box_name = clean_wikitext(params.get("name", "")).replace("\n", " ")
    out = {
        "title": title,
        "title_key": title_key(title),
        "box": box,
        "latin": latin,
        "latin_key": join_key(latin),
        "authority": clean_wikitext(params.get("authority", "")).replace("\n", " "),
        "status": conservation(params),
        "synonyms": synonym_names(params.get("synonyms", "")),
        "common_names": common_names(title, box_name, lead, latin),
        "lead": clean_wikitext(lead),
        "categories": [c.strip() for c in CATEGORY_RE.findall(text)],
    }
    out.update(section_attributes(sections))
    return out
