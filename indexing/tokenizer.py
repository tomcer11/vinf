"""
Tokenizer: the text of a Tree -> terms of the full-text index. The same
tokenize() is used for the queries.

  1. normalize     lower case, no accents (Krüssmann -> krussmann), dashes as '-'
  2. URLs          https://hgic.clemson.edu/..., www.ipni.org are dropped
  3. citations     a parenthesis with a year is dropped whole:
                   (Bean 1981), (Hardin 1957a, 1957c), (Landrein et al. 2017; Dirr 2009)
  4. short values  'hardiness:4-7', 'exposure:full_sun' ... see value_tokens()
  5. words         whole words of [a-z0-9]; hyphens and apostrophes split them:
                   well-drained -> well drained, Bean's -> bean s
  6. filters       no numbers (years, sizes), no single letters (x, m, s),
                   no stop words
  7. stemming      Porter (porter.py), only for words of letters: leaves -> leav,
                   h7 and 2n stay as they are

  "Deciduous trees for well-drained soils (Bean 1981), to 50 m"
      -> decidu tree well drain soil

Short values are not stemmed. Zone ranges are written out, so that
hardiness:5 finds a plant of the zones 4-7:
  hardiness:4-7      -> hardiness:4 hardiness:5 hardiness:6 hardiness:7
  hardiness:8b-9a    -> hardiness:8 hardiness:9        (sub-zones dropped)
  exposure:full_sun  -> exposure:full_sun

Usage:
  python -m indexing.tokenizer                 # statistics of the tokens of output/data/trees.jsonl
  python -m indexing.tokenizer --text "..."    # tokens of one text or query
"""

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from extractor.tree import Tree
from indexing.porter import stem

TREES_PATH = Path("./output/data/trees.jsonl")

# Letters that NFKD does not split into a base letter and an accent
SPECIAL_LETTERS = str.maketrans({"æ": "ae", "œ": "oe", "ø": "o", "ß": "ss", "–": "-", "—": "-"})

# A URL ends before a parenthesis, so that "(Flora 2005; www.ipni.org)" stays a citation
URL_RE = re.compile(r"(?:https?://|www\.)[^\s()<>]+")
CITATION_RE = re.compile(r"\([^()]*\b(?:1[5-9]|20)\d\d[a-z]?\b[^()]*\)")
WORD_RE = re.compile(r"[a-z0-9]+")

# Names of the short values written by the extractors ("hardiness:4-7")
VALUE_NAMES = ("hardiness", "heat_zone", "rhs", "conservation", "plant_type", "exposure",
               "season", "height", "spread", "water", "soil", "ph", "drainage")
VALUE_RE = re.compile(r"\b(?:" + "|".join(VALUE_NAMES) + r"):[a-z0-9._-]+")
ZONE_NAMES = ("hardiness", "heat_zone")
ZONE_RE = re.compile(r"\d+")

# English stop words, "et al." and the like, the halves of contractions split
# at the apostrophe (don't -> don t), and units of sizes whose numbers are dropped
STOPWORDS = set("""
a about above after again against all also although am an and any are as at be because been
before being below between both but by can could did do does doing down during each either
etc few for from further had has have having he her here hers herself him himself his how
however i if in into is it its itself just may me might more most much must my myself no nor
not now of off often on once only or other ought our ours ourselves out over own per same she
should so some such than that the their theirs them themselves then there these they this
those through thus to too under until up upon very via was we were what when where whether
which while who whom whose why will with within without would yet you your yours yourself
et al eg ie cf
don doesn didn isn aren wasn weren won wouldn shouldn couldn hasn haven hadn ll ve re
cm mm ft km
""".split())

# Fields of a Tree and how they are tokenized
TEXT_FIELDS = (
    "name", "family", "genus", "common_names", "synonyms", "cultivars",
    "tso_authors", "tso_description", "tso_genus_description", "tso_distribution", "tso_habitat",
    "gardenia_description", "gardenia_highlights", "gardenia_origin",
)
VALUE_FIELDS = (
    "tso_hardiness", "tso_rhs", "tso_conservation",
    "gardenia_plant_type", "gardenia_hardiness", "gardenia_heat_zones", "gardenia_exposure",
    "gardenia_season", "gardenia_height", "gardenia_spread", "gardenia_water", "gardenia_soil",
    "gardenia_ph", "gardenia_drainage",
)
NOT_TOKENIZED = ("key", "sources", "urls")


def normalize(text: str) -> str:
    """Lower case, accents removed, dashes as '-': 'Épicéa – Krüssmann' -> 'epicea - krussmann'."""
    text = unicodedata.normalize("NFKD", text.lower().translate(SPECIAL_LETTERS))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def dropped(word: str) -> str:
    """Why a word is not a term: 'number', 'single letter', 'stop word', or ''."""
    if word.isdigit():
        return "number"
    if len(word) == 1:
        return "single letter"
    if word in STOPWORDS:
        return "stop word"
    return ""


def _prepare(text: str) -> str:
    return CITATION_RE.sub(" ", URL_RE.sub(" ", normalize(text)))


def _words(text: str) -> list[str]:
    return [word for word in WORD_RE.findall(text) if not dropped(word)]


def _term(word: str) -> str:
    return stem(word) if word.isalpha() else word


def words(text: str) -> list[str]:
    """The words of a text that become terms, before stemming (short values
    left out): 'Deciduous trees (Bean 1981)' -> ['deciduous', 'trees']."""
    return _words(VALUE_RE.sub(" ", _prepare(text)))


def value_tokens(value: str) -> list[str]:
    """One short value as tokens. A zone range is written out, sub-zones and
    the odd separators of TSO dropped ('hardiness:9-_10' -> hardiness:9
    hardiness:10); other values stay one token. '' -> []."""
    value = value.strip().rstrip("._-")
    name, _, rest = value.partition(":")
    zones = [int(zone) for zone in ZONE_RE.findall(rest)] if name in ZONE_NAMES else []
    if zones:
        return [f"{name}:{zone}" for zone in range(min(zones), max(zones) + 1)]
    return [value] if rest else []


def tokenize(text: str) -> list[str]:
    """Terms of a text or a query, in the order of the text."""
    text = _prepare(text)
    tokens, start = [], 0
    for match in VALUE_RE.finditer(text):
        tokens += [_term(word) for word in _words(text[start:match.start()])]
        tokens += value_tokens(match.group(0))
        start = match.end()
    tokens += [_term(word) for word in _words(text[start:])]
    return tokens


def _items(value) -> list[str]:
    return value if isinstance(value, list) else [value]


def tree_tokens(tree: Tree) -> dict[str, list[str]]:
    """Terms of every text and short value field of a Tree, by field."""
    out = {}
    for name in TEXT_FIELDS:
        out[name] = [token for item in _items(getattr(tree, name)) for token in tokenize(item)]
    for name in VALUE_FIELDS:
        out[name] = [token for item in _items(getattr(tree, name)) for token in value_tokens(item)]
    return out


def print_statistics(trees: list[Tree]):
    all_words, removed = 0, Counter()
    distinct_words, text_terms, value_terms, by_field = set(), Counter(), Counter(), Counter()
    for tree in trees:
        for name in TEXT_FIELDS:
            for item in _items(getattr(tree, name)):
                text = normalize(item)
                found = WORD_RE.findall(text)
                text = URL_RE.sub(" ", text)
                outside_urls = WORD_RE.findall(text)
                kept = WORD_RE.findall(VALUE_RE.sub(" ", CITATION_RE.sub(" ", text)))
                all_words += len(found)
                removed["in URLs"] += len(found) - len(outside_urls)
                removed["in citations"] += len(outside_urls) - len(kept)
                for word in kept:
                    reason = dropped(word)
                    if reason:
                        removed[reason] += 1
                    else:
                        distinct_words.add(word)
        for name, tokens in tree_tokens(tree).items():
            by_field[name] += len(tokens)
            (value_terms if name in VALUE_FIELDS else text_terms).update(tokens)

    print(f"Trees: {len(trees)}")
    print("\nText fields")
    print(f"  {'words':45} {all_words:10}")
    for reason in ("in URLs", "in citations", "number", "single letter", "stop word"):
        print(f"  {'removed: ' + reason:45} {removed[reason]:10}")
    print(f"  {'tokens':45} {sum(text_terms.values()):10}")
    print(f"  {'distinct words before stemming':45} {len(distinct_words):10}")
    print(f"  {'distinct terms after stemming':45} {len(text_terms):10}")

    print("\nShort values")
    print(f"  {'tokens (zone ranges written out)':45} {sum(value_terms.values()):10}")
    print(f"  {'distinct terms':45} {len(value_terms):10}")

    print("\nTokens per field")
    for name, count in by_field.most_common():
        print(f"  {name:45} {count:10}")

    print("\nMost frequent terms of the text fields")
    for term, count in text_terms.most_common(20):
        print(f"  {term:45} {count:10}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--text", help="print the tokens of this text instead of the statistics")
    args = parser.parse_args()

    if args.text is not None:
        print(" ".join(tokenize(args.text)))
        return
    with TREES_PATH.open(encoding="utf-8") as lines:
        trees = [Tree.from_dict(json.loads(line)) for line in lines]
    print_statistics(trees)


if __name__ == "__main__":
    main()
