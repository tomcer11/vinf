"""
Extraction of gardenia.net plant pages (crawled_pages/gardenia/pages/plant_*.html), REGEX only.

A plant page has:
  <h1 class="h3">Fagus sylvatica &#8216;Pendula&#8217; (European Beech)</h1>
  <p class="h5"><em>European Beech 'Pendula', Common Beech 'Pendula', ...</em></p>
  <div class="single-section__main-text">
                   <p> description ("... large, deciduous tree ... leaves ...")
                   <ul><li> highlights ("Grows up to ...", "Native to ...")
                   some plants have a long article here instead, with a table
                   of contents and <h2> sections; the block always ends at
                   <div class="button-group-wrapper"> (Buy / Add to Collection)
  <h3>Requirements</h3><table> rows <th>Hardiness</th><td>4 - 7 <button ...></td>
"""

import re

from extractor.tree import clean_html, short_value, short_values

MAIN_TEXT_START = '<div class="single-section__main-text">'
MAIN_TEXT_END = '<div class="button-group-wrapper">'
REQUIREMENTS_START = ">Requirements<"

H1_RE = re.compile(r'<h1 class="h3">(.*?)</h1>', re.DOTALL)
SUBTITLE_RE = re.compile(r'</h1>\s*<p class="h5"><em>(.*?)</em>', re.DOTALL)
TRAILING_COMMON_RE = re.compile(r"\s*\([^()]*\)\s*$")
P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL)
LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.DOTALL)
ROW_RE = re.compile(r"<th>(.*?)</th>\s*<td>(.*?)</td>", re.DOTALL)
BUTTON_RE = re.compile(r"<button.*?</button>", re.DOTALL)
PARENS_RE = re.compile(r"\(([^()]*)\)")
PLANT_TYPE_RE = re.compile(r"<th>Plant Type</th>\s*<td>(.*?)</td>", re.DOTALL)

TREE_TYPES = ("trees", "shrubs", "conifers")


def plant_type(html: str) -> list[str]:
    """Plant Type cell as short values, e.g. ['plant_type:shrubs', 'plant_type:trees']."""
    match = PLANT_TYPE_RE.search(html)
    return short_values("plant_type", clean_html(match.group(1))) if match else []


def is_tree_or_shrub(types: list[str]) -> bool:
    return any(t.split(":", 1)[1] in TREE_TYPES for t in types)


def title_name(html: str) -> str:
    """Latin name from the title: 'Fagus sylvatica ‘Pendula’ (European Beech)'
    -> 'Fagus sylvatica ‘Pendula’'."""
    h1 = H1_RE.search(html)
    return TRAILING_COMMON_RE.sub("", clean_html(h1.group(1))) if h1 else ""


def requirements(html: str) -> dict[str, str]:
    """Cleaned cells of the Requirements table, by row heading."""
    start = html.find(REQUIREMENTS_START)
    if start < 0:
        return {}
    end = html.find("</table>", start)
    table = html[start:end if end >= 0 else len(html)]
    rows = {}
    for match in ROW_RE.finditer(table):
        rows[clean_html(match.group(1))] = clean_html(BUTTON_RE.sub("", match.group(2)))
    return rows


def metric(cell: str) -> str:
    """"35' - 50' (10.7m - 15.2m)" -> '10.7m - 15.2m' (the metric part in parentheses)."""
    match = PARENS_RE.search(cell)
    return match.group(1) if match else cell


def split_names(cell: str) -> list[str]:
    return [name.strip() for name in cell.split(",") if name.strip()]


def parse_gardenia_plant(html: str) -> dict:
    """Fields of a Tree from one gardenia plant page (keys as in tree.Tree,
    plus 'title_common_names', the names under the title)."""
    out = {"name": title_name(html)}
    subtitle = SUBTITLE_RE.search(html)
    out["title_common_names"] = split_names(clean_html(subtitle.group(1))) if subtitle else []

    start = html.find(MAIN_TEXT_START)
    if start >= 0:
        start += len(MAIN_TEXT_START)
        end = html.find(MAIN_TEXT_END, start)
        main = html[start:end if end >= 0 else len(html)]
    else:
        main = ""
    paragraphs = [clean_html(p) for p in P_RE.findall(main)]
    out["gardenia_description"] = "\n".join(p for p in paragraphs if p)
    highlights = [clean_html(li) for li in LI_RE.findall(main)]
    out["gardenia_highlights"] = [h for h in highlights if h]
    out["gardenia_origin"] = next(
        (h for h in out["gardenia_highlights"] if h.lower().startswith("native to")), "")

    rows = requirements(html)
    out["family"] = rows.get("Plant Family", "")
    out["genus"] = rows.get("Genus", "")
    out["common_names"] = split_names(rows.get("Common names", ""))
    out["gardenia_plant_type"] = short_values("plant_type", rows.get("Plant Type", ""))
    out["gardenia_hardiness"] = short_value("hardiness", rows.get("Hardiness", ""))
    out["gardenia_heat_zones"] = short_value("heat_zone", rows.get("Heat Zones", ""))
    out["gardenia_exposure"] = short_values("exposure", rows.get("Exposure", ""))
    out["gardenia_season"] = short_values("season", PARENS_RE.sub("", rows.get("Season of Interest", "")))
    out["gardenia_height"] = short_value("height", metric(rows.get("Height", "")))
    out["gardenia_spread"] = short_value("spread", metric(rows.get("Spread", "")))
    out["gardenia_water"] = short_values("water", rows.get("Water Needs", ""))
    out["gardenia_soil"] = short_values("soil", rows.get("Soil Type", ""))
    out["gardenia_ph"] = short_values("ph", rows.get("Soil pH", ""))
    out["gardenia_drainage"] = short_values("drainage", rows.get("Soil Drainage", ""))
    return out
