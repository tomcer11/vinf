"""
The Tree record and the text helpers shared by both extractors.

One Tree = one species (or one TSO page that is not a plain species: a hybrid,
a subspecies, a cultivar group ...). Trees and Shrubs Online (tso_*) and
gardenia.net (gardenia_*) keep their texts in separate fields.

Field kinds:
  paragraphs     whole cleaned paragraphs, e.g. tso_habitat
  short values   "name:value" strings, e.g. "hardiness:4-7", or lists of them
  name lists     common_names, synonyms, cultivars
"""

import html as htmllib
import re
from dataclasses import asdict, dataclass, field, fields

RANKS = {"subsp.", "ssp.", "var.", "f.", "subvar."}
HYBRID_SIGNS = {"x", "×"}

# A specific epithet: lowercase latin word of at least 3 letters, a hyphen is
# allowed inside (uva-ursi). "in", "agg." or "'Pendula'" are not epithets.
EPITHET_RE = re.compile(r"^[a-zë][a-zë-]+[a-zë]$")

# Block tags separate words, inline tags (<i>, <a>, <span> ...) do not:
# "(<a ...>Tutin <i>et al</i>. 1993</a>)" -> "(Tutin et al. 1993)"
BLOCK_TAG_RE = re.compile(r"</?(?:p|br|li|ul|ol|div|td|th|tr|table|h\d)\b[^>]*>", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
# Bean's fractions: 2<span class=fnum>1</span>⁄<span class=fden>2</span> -> 2 1/2
FRACTION_RE = re.compile(r"<span class=fnum>(\d+)</span>\s*⁄\s*<span class=fden>(\d+)</span>")
VALUE_JUNK_RE = re.compile(r"[^a-z0-9.\-]+")


@dataclass
class Tree:
    # identity
    key: str
    name: str
    sources: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)

    # taxonomy and names, shared by both sources
    family: str = ""
    genus: str = ""
    common_names: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    cultivars: list[str] = field(default_factory=list)

    # Trees and Shrubs Online: paragraphs
    tso_authors: str = ""
    tso_description: str = ""
    tso_genus_description: str = ""
    tso_distribution: str = ""
    tso_habitat: str = ""

    # Trees and Shrubs Online: short values
    tso_hardiness: str = ""
    tso_rhs: str = ""
    tso_conservation: str = ""

    # gardenia.net: texts
    gardenia_description: str = ""
    gardenia_highlights: list[str] = field(default_factory=list)
    gardenia_origin: str = ""

    # gardenia.net: short values
    gardenia_plant_type: list[str] = field(default_factory=list)
    gardenia_hardiness: str = ""
    gardenia_heat_zones: str = ""
    gardenia_exposure: list[str] = field(default_factory=list)
    gardenia_season: list[str] = field(default_factory=list)
    gardenia_height: str = ""
    gardenia_spread: str = ""
    gardenia_water: list[str] = field(default_factory=list)
    gardenia_soil: list[str] = field(default_factory=list)
    gardenia_ph: list[str] = field(default_factory=list)
    gardenia_drainage: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Tree":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def add_unique(self, list_name: str, values: list[str]):
        """Append values to a list field, skipping case-insensitive duplicates."""
        target = getattr(self, list_name)
        seen = {v.lower() for v in target}
        for value in values:
            if value and value.lower() not in seen:
                seen.add(value.lower())
                target.append(value)


def clean_html(fragment: str) -> str:
    """Plain text of an HTML fragment: no tags, entities decoded (&ensp;,
    &thinsp; and &nbsp; become ordinary spaces), no soft hyphens, whitespace
    collapsed."""
    text = FRACTION_RE.sub(r" \1/\2", fragment)
    text = BLOCK_TAG_RE.sub(" ", text)
    text = TAG_RE.sub("", text)
    text = htmllib.unescape(text).replace("\xad", "")     # soft hyphen U+00AD
    return SPACE_RE.sub(" ", text).strip()


def normalize_quotes(text: str) -> str:
    return text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')


def normalize_value(value: str) -> str:
    """'Full Sun' -> 'full_sun', '4 - 7' -> '4-7', 'Cactus & Succulents' ->
    'cactus_and_succulents'."""
    value = value.lower().replace("&", " and ").replace("–", "-").replace("—", "-")
    value = re.sub(r"\s*-\s*", "-", value.strip())
    return VALUE_JUNK_RE.sub("_", value).strip("_")


def short_value(name: str, value: str) -> str:
    """One short value as 'name:value', or '' if the value is empty."""
    value = normalize_value(value)
    return f"{name}:{value}" if value else ""


def short_values(name: str, values: str, sep: str = ",") -> list[str]:
    """A comma separated cell as a list of 'name:value' strings."""
    out = []
    for part in values.split(sep):
        item = short_value(name, part)
        if item and item not in out:
            out.append(item)
    return out


def name_key(latin: str) -> str:
    """The whole latin name as a lookup key: lowercase, straight quotes,
    '×' for hybrids, no trademark signs, single spaces."""
    text = normalize_quotes(latin).replace("®", "").replace("™", "")
    tokens = ["×" if t.lower() in HYBRID_SIGNS else t for t in text.split()]
    return " ".join(tokens).lower()


def species_key(latin: str) -> tuple[str, str]:
    """(key of the taxon without cultivar, cultivar part).

    'Fagus sylvatica'                  -> ('fagus sylvatica', '')
    "Fagus sylvatica 'Pendula'"        -> ('fagus sylvatica', 'Pendula')
    "Caryopteris x clandonensis 'Kew Blue'"
                                       -> ('caryopteris × clandonensis', 'Kew Blue')
    'Pinus mugo var. pumilio'          -> ('pinus mugo var. pumilio', '')
    'Hydrangea paniculata Quick Fire Fab®'
                                       -> ('hydrangea paniculata', 'Quick Fire Fab')
    Names without an epithet ("Abelia 'Edward Goucher'", 'Abies in Mexico')
    or hybrid formulas ('Acer platanoides × amplum') are keyed by the whole
    name and have no cultivar part.
    """
    tokens = normalize_quotes(latin).replace("®", "").replace("™", "").split()
    if not tokens:
        return "", ""
    whole = (name_key(latin), "")

    i = 0
    key = []
    if tokens[0].lower() in HYBRID_SIGNS:          # intergeneric hybrid: × Chitalpa
        key.append("×")
        i = 1
    if i >= len(tokens):
        return whole
    key.append(tokens[i])                          # genus
    i += 1

    if i + 1 < len(tokens) and tokens[i].lower() in HYBRID_SIGNS and EPITHET_RE.match(tokens[i + 1]):
        key += ["×", tokens[i + 1]]
        i += 2
    elif i < len(tokens) and EPITHET_RE.match(tokens[i]):
        key.append(tokens[i])
        i += 1
    else:
        return whole

    while i + 1 < len(tokens) and tokens[i] in RANKS and EPITHET_RE.match(tokens[i + 1]):
        key += [tokens[i], tokens[i + 1]]
        i += 2

    rest = tokens[i:]
    if rest and (rest[0].lower() in HYBRID_SIGNS or rest[0] in ("+", "agg.")):
        return whole
    cultivar = " ".join(rest).strip("'\" ")
    return " ".join(key).lower(), cultivar


def latin_part(text: str) -> str:
    """The latin name at the start of a text, without the authors that follow:
    'Linnaea chinensis (R. Br.) A. Braun & Vatke' -> 'Linnaea chinensis'."""
    tokens = text.split()
    if not tokens:
        return ""
    out = [tokens[0]]
    for token in tokens[1:]:
        if EPITHET_RE.match(token) or token in RANKS or token.lower() in HYBRID_SIGNS:
            out.append(token)
        else:
            break
    return " ".join(out)
