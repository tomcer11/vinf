"""
Porter's stemmer as published in M. F. Porter, "An algorithm for suffix
stripping", Program 14(3), 1980, pp. 130-137. Written by hand, NLTK is not
allowed in the course.

Terms of the paper:
  consonant  a letter other than a, e, i, o, u, and other than y preceded by
             a consonant (the y of "toy" is a consonant, of "syzygy" a vowel)
  m          the measure of a stem written as [C](VC)^m[V]:
             m=0 tree, by    m=1 trouble, oats    m=2 troubles, private
  *v*        the stem contains a vowel
  *d         the stem ends with a double consonant (-tt, -ss)
  *o         the stem ends consonant-vowel-consonant and the last consonant
             is not w, x or y (-wil, -hop)

Of the rules of one step only the one with the longest matching suffix is
tried, and when its condition fails the word stays as it is: "agreement"
keeps EMENT (m of "agre" is 1) and is not cut by ENT.

  generalizations -> generalization -> generalize -> general -> gener
  leaves -> leav, flowering -> flower, deciduous -> decidu, fagus -> fagu
"""

from functools import lru_cache

VOWELS = "aeiou"

# The rules of the paper, sorted longest suffix first so that the first
# suffix a word ends with is the longest one
STEP1A = sorted([("sses", "ss"), ("ies", "i"), ("ss", "ss"), ("s", "")],
                key=lambda rule: len(rule[0]), reverse=True)
STEP2 = sorted([
    ("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"),
    ("izer", "ize"), ("abli", "able"), ("alli", "al"), ("entli", "ent"),
    ("eli", "e"), ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"),
    ("ator", "ate"), ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"),
    ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"),
], key=lambda rule: len(rule[0]), reverse=True)
STEP3 = sorted([
    ("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"),
    ("ical", "ic"), ("ful", ""), ("ness", ""),
], key=lambda rule: len(rule[0]), reverse=True)
STEP4 = sorted([
    "al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment",
    "ent", "ion", "ou", "ism", "ate", "iti", "ous", "ive", "ize",
], key=len, reverse=True)


def _is_consonant(word: str, i: int) -> bool:
    if word[i] in VOWELS:
        return False
    if word[i] == "y":
        return i == 0 or not _is_consonant(word, i - 1)
    return True


def _measure(stem: str) -> int:
    """m of [C](VC)^m[V]: the number of changes from a vowel to a consonant."""
    m = 0
    after_vowel = False
    for i in range(len(stem)):
        if _is_consonant(stem, i):
            if after_vowel:
                m += 1
            after_vowel = False
        else:
            after_vowel = True
    return m


def _has_vowel(stem: str) -> bool:
    return any(not _is_consonant(stem, i) for i in range(len(stem)))


def _ends_double_consonant(stem: str) -> bool:
    return len(stem) >= 2 and stem[-1] == stem[-2] and _is_consonant(stem, len(stem) - 1)


def _ends_cvc(stem: str) -> bool:
    n = len(stem)
    return (n >= 3 and _is_consonant(stem, n - 3) and not _is_consonant(stem, n - 2)
            and _is_consonant(stem, n - 1) and stem[-1] not in "wxy")


def _replace(word: str, rules: list[tuple[str, str]], min_measure: int) -> str:
    """Apply the rule with the longest suffix of the word when m of the stem
    is at least min_measure."""
    for suffix, replacement in rules:
        if word.endswith(suffix):
            stem = word[:-len(suffix)]
            return stem + replacement if _measure(stem) >= min_measure else word
    return word


def step1a(word: str) -> str:
    """Plurals: caresses -> caress, ponies -> poni, caress -> caress, cats -> cat."""
    return _replace(word, STEP1A, 0)


def step1b(word: str) -> str:
    """-eed, -ed, -ing: agreed -> agree, plastered -> plaster, motoring -> motor,
    and the tidying after -ed and -ing: hopping -> hop, filing -> file."""
    if word.endswith("eed"):
        return word[:-1] if _measure(word[:-3]) > 0 else word
    for suffix in ("ed", "ing"):
        if word.endswith(suffix):
            stem = word[:-len(suffix)]
            return _tidy_step1b(stem) if _has_vowel(stem) else word
    return word


def _tidy_step1b(stem: str) -> str:
    if stem.endswith(("at", "bl", "iz")):            # conflat(ed) -> conflate
        return stem + "e"
    if _ends_double_consonant(stem) and stem[-1] not in "lsz":
        return stem[:-1]                             # hopp(ing) -> hop, fall(ing) stays
    if _measure(stem) == 1 and _ends_cvc(stem):      # fil(ing) -> file
        return stem + "e"
    return stem


def step1c(word: str) -> str:
    """happy -> happi, sky -> sky."""
    if word.endswith("y") and _has_vowel(word[:-1]):
        return word[:-1] + "i"
    return word


def step2(word: str) -> str:
    """(m>0) relational -> relate, conformabli -> conformable."""
    return _replace(word, STEP2, 1)


def step3(word: str) -> str:
    """(m>0) triplicate -> triplic, goodness -> good."""
    return _replace(word, STEP3, 1)


def step4(word: str) -> str:
    """(m>1) revival -> reviv, adoption -> adopt (ION only after s or t)."""
    for suffix in STEP4:
        if word.endswith(suffix):
            stem = word[:-len(suffix)]
            if _measure(stem) > 1 and (suffix != "ion" or stem.endswith(("s", "t"))):
                return stem
            return word
    return word


def step5a(word: str) -> str:
    """probate -> probat, rate -> rate, cease -> ceas."""
    if word.endswith("e"):
        stem = word[:-1]
        m = _measure(stem)
        if m > 1 or (m == 1 and not _ends_cvc(stem)):
            return stem
    return word


def step5b(word: str) -> str:
    """controll -> control, roll -> roll."""
    if _measure(word) > 1 and _ends_double_consonant(word) and word.endswith("l"):
        return word[:-1]
    return word


STEPS = (step1a, step1b, step1c, step2, step3, step4, step5a, step5b)


@lru_cache(maxsize=None)
def stem(word: str) -> str:
    """Stem of a lower case word of the letters a-z. Words of one or two
    letters are not stemmed."""
    if len(word) <= 2:
        return word
    for step in STEPS:
        word = step(word)
    return word
