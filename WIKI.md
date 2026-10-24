# Vyhľadávanie informácií – dreviny (Trees and Shrubs Online + gardenia.net)

Odovzdanie prvej časti projektu (28. 10. 2026). Kód: [github.com/tomcer11/vinf](https://github.com/tomcer11/vinf), ZIP `odovzdanie.zip`.

## 1. Opis projektu a cieľ

**TLDR:** vyhľadávač drevín. Používateľ zadá anglický dopyt – chorobu, škodcu, prostredie, vedecké
meno alebo synonymum, USDA zónu … – a systém vráti zoradený zoznam drevín, ktoré s ním súvisia,
spolu s vetou zo stránky, prečo.

**Motivácia:** údaje o drevinách sú roztrúsené. Odborná encyklopédia **Trees and Shrubs Online
(TSO)** má taxonómiu, rozšírenie, habitat, morfológiu a históriu druhov, no o škodcoch a pestovaní
píše málo. Záhradnícka databáza **gardenia.net** má presne to (USDA zóny, škodcovia, pôda,
tolerancie, toxicita), ale aj trvalky, cibuľoviny a trávy. Preto je TSO hlavný zoznam drevín
a rastliny z gardenie sú naň **namapované** – do indexu sa dostanú len dreviny a ich gardenia
údaje obohatia dokument TSO.

```
crawl_articles.py ──> pages/ ──────────┐                ┌─> data/tso.jsonl ──────┐
                                       ├─> extractor.py ─┤                        ├─> mapping.py ─> data/trees.jsonl ─> indexer.py ─> index/index.json.gz ─> search.py
crawl_gardenia.py ──> gardenia/pages/ ─┘    (REGEX)      └─> data/gardenia.jsonl ─┘  gardenia → TSO                    (vlastný index)                     (dopyty)
```

| súbor | čo robí |
|---|---|
| `crawler_config.py` | spoločná zdvorilá HTTP session: robots.txt, oneskorenie, cache, log |
| `crawl_articles.py`, `crawl_gardenia.py` | crawlery oboch stránok |
| `extractor.py` | REGEX extraktor: HTML → JSON záznam na stránku |
| `mapping.py` | mapovanie gardenia → TSO, zlúčené dokumenty |
| `indexer.py` | vlastný invertovaný index (TF), 3 metódy idf, TF-IDF a BM25 |
| `search.py` | dopytovací jazyk, filtre, karta druhu, porovnanie idf |
| `stats.py` | štatistika dát + tokeny tiktoken |
| `tests/test_extractor.py` | unit testy REGEX extraktorov |

---

## 2. Scrapované stránky a extrahované dáta

| stránka | čo sa sťahuje | aké dáta sú zaujímavé |
|---|---|---|
| [treesandshrubsonline.org/articles](https://www.treesandshrubsonline.org/articles/) | 26 abecedných zoznamov a–z → stránky rodov a druhov (do úrovne `/articles/<rod>/<druh>/`) | čeľaď, rod, bežné mená, synonymá, rozšírenie (krajiny), habitat, nadmorská výška, morfológia, výška, USDA zóna, RHS, IUCN status, kultivary a ich iné mená, škodcovia a choroby z textu článku |
| [gardenia.net/plants/genera](https://www.gardenia.net/plants/genera) + sitemap | index rodov → stránky rodov → stránky rastlín `/plant/<slug>`; chýbajúce rastliny zo `plant-sitemap*.xml` | typ rastliny, USDA zóna, výška a šírka, expozícia, pôda, tolerancie, láka (vtáky, motýle), toxicita, pôvod, škodcovia a choroby, vedecké synonymá |

### 2.1 Päť ukážok extrahovaných dát

Výstup `extractor.py` (skrátené dlhé texty a zoznamy). Celý záznam jednej stránky:
`python extractor.py --show pages/articles_picea_picea-abies.html`.

**1. TSO, moderný článok – Picea abies**
```json
{
  "url": "https://www.treesandshrubsonline.org/articles/picea/picea-abies/",
  "kind": "species",
  "title": "Picea abies",
  "family": "Pinaceae",
  "genus": "Picea",
  "common_names": [
    "Norway Spruce",
    "Gemeine Fichte",
    "Epicéa Commun",
    "Jel Europeiskaya",
    "… (+1)"
  ],
  "synonym_names": [
    "Picea abies var. alpestris",
    "Picea abies var. arctica",
    "Picea abies subsp. europaea",
    "Picea abies subsp. subalpinum",
    "… (+9)"
  ],
  "countries": [
    "Albania",
    "Austria",
    "Belarus",
    "Bosnia and Herzegovina",
    "… (+26)"
  ],
  "habitat": "Variable over an extensive range. Widespread in the boreal conifer forests of northern Europe (Norway, Sweden, Finland, NW Russia etc.) from sea level …",
  "habitat_from_text": "Furthermore, P. abies has been shown to be an important habitat and food source for a range of biodiversity even outside its native range, notably the …",
  "usda": {
    "raw": "4",
    "min": 4,
    "max": null
  },
  "rhs": "H7",
  "conservation": "LC",
  "height": {
    "raw": "40–60 m",
    "min_m": 40.0,
    "max_m": 60.0
  },
  "life_form": [
    "tree"
  ],
  "leaf_habit": [
    "evergreen"
  ],
  "mountain": true,
  "mountain_terms": [
    "alps",
    "carpathians",
    "mountains"
  ],
  "pest_sentences": [
    "Warming temperatures alone pose an acute threat to this species, with northern range contractions expected in areas such as southern Scandinavia (Caud …",
    "An extraordinary plant, this is truly one for a collector: a single, usually unbranched protrusion erupting from the ground like an alien fungus, bear …"
  ],
  "sections": [
    {
      "id": "30965",
      "name": "'Aarburg'",
      "synonyms": []
    },
    {
      "id": "30966",
      "name": "'Abishenski Pendula'",
      "synonyms": []
    },
    "… (+78)"
  ]
}
```

**2. TSO, starší článok z knihy W. J. Beana (bez súhrnného bloku) – Pinus cembra.** Habitat
sa skladá z viet článku, výška je v stopách, horské prostredie podľa „Alps, Tatras“ a „5,000 ft“.
```json
{
  "url": "https://www.treesandshrubsonline.org/articles/pinus/pinus-cembra/",
  "kind": "species",
  "title": "Pinus cembra",
  "family": "Pinaceae",
  "genus": "Pinus",
  "common_names": [
    "Arolla Plne"
  ],
  "habitat_from_text": "Native of the Alps, from France to Lower Austria, and of the Tatras and Carpathians, rarely descending below 5,000 ft. In the Alps it occurs in the in …",
  "height": {
    "raw": "60 to over 100 ft",
    "min_m": 18.29,
    "max_m": 30.48
  },
  "life_form": [
    "tree"
  ],
  "altitude": {
    "min_m": 1524,
    "max_m": 1524
  },
  "mountain": true,
  "mountain_terms": [
    "alps",
    "carpathians",
    "limit of tree growth",
    "tatras"
  ]
}
```

**3. TSO, stránka s redakčnou poznámkou – Ailanthus altissima.** Poznámka sa uloží zvlášť
a neodreže zvyšok súhrnného bloku.
```json
{
  "url": "https://www.treesandshrubsonline.org/articles/ailanthus/ailanthus-altissima/",
  "kind": "species",
  "title": "Ailanthus altissima",
  "family": "Simaroubaceae",
  "genus": "Ailanthus",
  "common_names": [
    "Tree of Heaven",
    "Chinese Sumach",
    "Heavenwood",
    "Paradise Tree",
    "… (+7)"
  ],
  "synonym_names": [
    "Ailanthus altissima var. leucoxyla",
    "Ailanthus altissima var. microphylla",
    "Ailanthus altissima var. ramosissima",
    "Ailanthus cacodendron",
    "… (+6)"
  ],
  "countries": [
    "China",
    "Vietnam",
    "Taiwan"
  ],
  "habitat": "Mountain forests and open woodlands in its native habitat. As an invasive it now occurs in many habitats around the world, especially in urban and per …",
  "habitat_from_text": "Var. altissima does not grow wild in Taiwan (Li 1993). Except in the northern Prairie states where winters are too harsh for the species to persist, A …",
  "usda": {
    "raw": "5a",
    "min": 5,
    "max": null
  },
  "rhs": "H6",
  "conservation": "NE",
  "height": {
    "raw": "30 m",
    "min_m": 30.0,
    "max_m": 30.0
  },
  "life_form": [
    "tree"
  ],
  "mountain": true,
  "mountain_terms": [
    "mountain"
  ],
  "pests": [
    "mite"
  ],
  "pest_sentences": [
    "A yellow dye is derived from the foliage, which can also be used as an insect repellant (Quantrell 2024).",
    "The silk produced by this moth’s larvae is stronger – and cheaper – but less smooth and shiny than the silk of Bombyx mori (which feeds on mulberry le …",
    "This fabric’s Chinese name translates as ‘peace silk’ since the fibres can be harvested after the larvae have flown, without harming them (Battles 202 …",
    "Male trees were selected against – their smelly flowers and pollen that can also be allergenic (Enescu, Houston Durrant & Caudullo 2016), but they do …",
    "… (+5)"
  ],
  "editorial_note": "The International Dendrology Society does not condone the cultivation of Ailanthus altissima.",
  "sections": [
    {
      "id": "8932",
      "name": "'Erythrocarpa'",
      "synonyms": [
        "Ailanthus erythrocarpus Carrière",
        "Ailanthus altissima f. erythrocarpa (Carrière) Rehder"
      ]
    },
    {
      "id": "30848",
      "name": "'Metro'",
      "synonyms": []
    },
    "… (+5)"
  ]
}
```

**4. gardenia – Picea abies**
```json
{
  "url": "https://www.gardenia.net/plant/picea-abies",
  "title": "Picea abies (Norway Spruce)",
  "scientific_name": "Picea abies",
  "common_names": [
    "Norway Spruce",
    "European Spruce",
    "Baltic Whitewood",
    "Burgundy Pitch Tree",
    "… (+3)"
  ],
  "plant_type": [
    "Conifers",
    "Trees"
  ],
  "usda": {
    "raw": "3 - 8",
    "min": 3,
    "max": 8
  },
  "height": {
    "min_m": 12.2,
    "max_m": 18.3
  },
  "exposure": [
    "Full Sun"
  ],
  "soil_ph": [
    "Acid",
    "Neutral"
  ],
  "tolerances": [
    "Deer",
    "Clay Soil",
    "Wind"
  ],
  "attracts": [
    "Birds"
  ],
  "toxic_dogs": "No known toxicity",
  "native_to": "Europe",
  "pests": [
    "adelgid",
    "aphid",
    "spider mite"
  ],
  "pest_sentences": [
    "Watch for adelgids, aphids and conifer red spider mite."
  ],
  "habitat_sentences": [
    "Picea abies species is native to Europe."
  ]
}
```

**5. gardenia – Castanea dentata.** „Castanea americana“ je medzi bežnými menami, extraktor ju
rozpozná ako vedecké synonymum.
```json
{
  "url": "https://www.gardenia.net/plant/castanea-dentata-american-chestnut-grow-care-guide",
  "title": "Castanea dentata (American Chestnut)",
  "scientific_name": "Castanea dentata",
  "common_names": [
    "American Chestnut",
    "Chestnut",
    "American Sweet Chestnut"
  ],
  "scientific_synonyms": [
    "Castanea americana"
  ],
  "plant_type": [
    "Trees"
  ],
  "usda": {
    "raw": "5 - 8",
    "min": 5,
    "max": 8
  },
  "height": {
    "min_m": 15.2,
    "max_m": 24.4
  },
  "exposure": [
    "Full Sun",
    "Partial Sun"
  ],
  "soil_ph": [
    "Acid",
    "Neutral"
  ],
  "tolerances": [
    "Clay Soil"
  ],
  "attracts": [
    "Butterflies"
  ],
  "toxic_dogs": "Not toxic",
  "native_to": "the eastern United States and southeastern Canada",
  "pests": [
    "aphid",
    "blight",
    "borer",
    "deer",
    "… (+4)"
  ],
  "pest_sentences": [
    "Historically, it was a crucial source of timber and food, but its population was devastated by chestnut blight in the early 20th century.",
    "The tree can form a multi-stemmed shrub if blight repeatedly kills the main trunk, allowing the roots to sprout new growth.",
    "In contemporary times, surviving trees (stump sprouts) rarely exceed 20 feet (6 meters) in height before succumbing to blight infection again.",
    "The chestnut blight primarily kills the above-ground portion of the tree, leaving the root systems intact.",
    "… (+14)"
  ],
  "habitat_sentences": [
    "Castanea dentata, commonly known as the American chestnut, is a large deciduous tree once a dominant species in the forests of eastern North America.",
    "Native: The American chestnut is native to the eastern United States and southeastern Canada."
  ]
}
```

### 2.2 Mapovanie gardenia → TSO

Platí prvé pravidlo, ktoré sedí (`mapping.py`):

| úroveň | pravidlo | príklad |
|---|---|---|
| `cultivar` | kultivar / varieta má sekciu na stránke TSO (`<h3 id=…>`), aj podľa jej iného mena | „Picea abies ‘Acrocona’“ → TSO Picea abies `#10731` |
| `species` | rod + druhové meno (+ znak ×) | „Picea abies ‘Little Gem’“ → TSO Picea abies |
| `synonym` | meno je synonymum na stránke TSO, alebo gardenia uvádza synonymum, ktoré je druhom v TSO | „Potentilla fruticosa ‘Abbotswood’“ → TSO Dasiphora fruticosa |
| `genus` | len rod má stránku v TSO **a** gardenia ho označuje ako drevinu (Trees, Shrubs, Conifers, Climbers, Roses, Palms, Bamboos) | „Clematis ‘Jackmanii Superba’“ → TSO Clematis; bylinná „Salvia nemorosa“ sa nenamapuje |
| `none` | nie je drevina z TSO | „Hepatica nobilis“ (trvalka) |

Nesprávne použité mená zo zoznamu synoným TSO („Potentilla nepalensis D.Don, **not Hook.**“,
„of many authors“, „auct.“) sa ignorujú.

| level | plants |
|---|---:|
| cultivar | 340 |
| species | 1685 |
| synonym | 173 |
| genus | 1032 |
| none | 6662 |
| **mapped** | **3230** (32.7 %) |

TSO pages with at least one gardenia plant: 1119; woody gardenia plants without a TSO genus: 392

---

## 3. Otázky a odpovede

Dopyty sa zadávajú po anglicky (`python search.py "<dopyt>"`, bez dopytu interaktívne):

| zápis | význam |
|---|---|
| `anthracnose`, `picea abies` | voľné slová – hľadá sa vo všetkých poliach, ranking s váhami polí |
| `pest:leafhopper`, `habitat:rainforest`, `synonym:excelsa` | slovo musí byť v poli (`title, name, synonym, cultivar, taxonomy, distribution/country, habitat, pest, morphology, garden/exposure/tolerance/soil, text`) |
| `pest:"powdery mildew"` | viac slov v jednom poli |
| `zone:5-8` | USDA: drevina prežije všetky zóny 5 až 8 (zóny TSO a gardenie zlúčené) |
| `status:EN,CR` | IUCN status (TSO) |
| `height:30-` | výška podľa TSO v metroch (`30-`, `-5`, `10-20`) |
| `toxic:dogs` | jedovaté podľa gardenie (dogs, cats, horses, humans) |
| `source:gardenia`, `kind:species` | len dreviny s rastlinami z gardenie; druh alebo rod |

Polia `pest` a `habitat` obsahujú **všetky** vety o škodcoch / chorobách a o prostredí z oboch
stránok, nielen tie, ktoré pozná zoznam regexov – preto funguje ľubovoľná choroba či prostredie.

### Otázka 1: Aké vlastnosti má *Picea abies*?
**Dopyt:** `Picea abies` – zhoda s vedeckým menom → karta druhu so všetkými vlastnosťami a pod ňou
zoradený zoznam. Taxonómia, výskyt, habitat, morfológia, RHS a IUCN sú zo stránky TSO; USDA zóny
z oboch stránok; škodcovia, pôda, tolerancie a toxicita z 13 namapovaných stránok gardenie.

```
python search.py "Picea abies" -k 3
query: 'Picea abies' -> free=['picea', 'aby'] fields={} filters={}
==============================================================================
  Picea abies   https://www.treesandshrubsonline.org/articles/picea/picea-abies/
==============================================================================
  Family / genus        Pinaceae / Picea
  Common names          Norway Spruce, Gemeine Fichte, Epicéa Commun, Jel Europeiskaya, Gran
  Synonyms (TSO)        13: Picea abies var. alpestris; Picea abies var. arctica; Picea abies subsp. europaea; Picea abies subsp. subalpinum; Picea alpestris; Picea excelsa ...
  Synonyms (gardenia)   Picea abies 'Inversa Pendula'; Picea abies 'Sherwood’s Multnomah'; Picea abies 'Sherwood'; Picea abies 'Sherwood Compact'; Picea abies 'Sherwood Gem'; Picea abies 'Acrocona Pusch'
  Distribution          Albania, Austria, Belarus, Bosnia and Herzegovina, Bulgaria, Croatia, Czechia, Estonia, Finland, France, Germany, Greece, Hungary, Italy, Latvia, Liechtenstein, Lithuania, North Macedonia, Moldova, Montenegro, Norway, Poland, Romania, Russia, Serbia, Slovakia, Slovenia, Sweden, Switzerland, Ukraine
  Habitat               Variable over an extensive range. Widespread in the boreal conifer forests of northern Europe (Norway, Sweden, Finland, NW Russia etc.) from sea level to several hundred metres asl, forming pure stands or in association with Pinus sylvestris, Juniperus communis, Betula pendula, Populus tremula, Sorb
  Mountain habitat      yes (alps, carpathians, mountains)
  Morphology            Tree 40–60 m tall, 1–1.5 dbh, rarely larger. Bark reddish-brown on young trees, soon rough to the touch, becoming paler with age and finally grey-brown in the lower trunk, breaking into irregular small plates. First order branches slender, soon spreading horizontally or bowed downward; second order 
  Height (TSO)          40.0-60.0 m
  Life form             tree, evergreen
  USDA zone (TSO)       4
  USDA zone (gardenia)  3 - 7, 3 - 8
  RHS rating            H7
  Conservation          Least concern (LC)
  Pests and diseases    adelgid, aphid, spider mite
    - aphid             Watch for adelgids, aphids and conifer red spider mite.
    - adelgid           Watch for adelgids, aphids and conifer red spider mite.
    - spider mite       Watch for adelgids, aphids and conifer red spider mite.
  Exposure              Full Sun
  Soil                  Clay, Loam, Sand, Acid, Neutral
  Tolerances            Deer, Clay Soil, Rabbit
  Attracts              Birds
  Toxic to dogs         No known toxicity
  gardenia plants       13: Picea abies ‘Acrocona’ (Norway Spruce); Picea abies ‘Cupressina’ (Norway Spruce); Picea abies ‘Inversa’ (Norway Spruce); Picea abies ‘Little Gem’ (Norway Spruce); Picea abies ‘Nidiformis’ (Norway Spruce); Picea abies ‘Pumila’ (Norway Spruce) ...

199 documents match  (model tfidf, idf classic)
  1.   7.904  Picea abies  (species | Norway Spruce, Gemeine Fichte | USDA 3-8 | IUCN LC | TSO + 13 gardenia)
            https://www.treesandshrubsonline.org/articles/picea/picea-abies/
            [habitat] Furthermore, P. abies has been shown to be an important habitat and food source for a range of biodiversity even outside its native range, notably the threatened Red Squirrel (Sciurus vulgaris) in northern Britain, wh...
  2.   5.751  Picea  (genus | Spruces | TSO)
            https://www.treesandshrubsonline.org/articles/picea/
            [pests] Another bark beetle, Ips typographus, commonly the Eight-toothed- or European Spruce-bark beetle, is indigenous across large parts of Europe (though not the UK or Ireland) and Asia, including the entire natural distri...
  3.   5.148  Picea maximowiczii  (species | Maximowicz Spruce, Japanese Bush Spruce | USDA 6-7 | IUCN EN | TSO)
            https://www.treesandshrubsonline.org/articles/picea/picea-maximowiczii/
            [habitat] A narrow endemic occurring in small, scattered populations over 1100–2000 m asl, usually in mixed coniferous-broadleaf forest on podzol soils with Picea alcoquiana, P. koyamae, P. torano and Pinus densiflora.
```

### Otázka 2: Ktoré dreviny rastú v horách?
**Dopyt:** `habitat:mountain` – dreviny, ktorých habitat spomína hory (mountain, montane, alpine,
tree line, meno pohoria Alps, Tatras, Himalaya …) alebo siaha do ≥ 1000 m n. m. Údaje sú z TSO:
pole Habitat, pri starších článkoch vety „Native of …“.

```
python search.py "habitat:mountain" -k 5
query: 'habitat:mountain' -> free=[] fields={'habitat': ['mountain']} filters={}

2186 documents match  (model tfidf, idf classic)
  1.   0.953  Abelia uniflora  (species | USDA 6+ | IUCN LC | TSO)
            https://www.treesandshrubsonline.org/articles/abelia/abelia-uniflora/
            [habitat] Mountain forests
  2.   0.953  Corylus jacquemontii  (species | West Himayalan Hazel | USDA 5+ | IUCN DD | TSO)
            https://www.treesandshrubsonline.org/articles/corylus/corylus-jacquemontii/
            [habitat] Mountain forests
  3.   0.953  Corylus × colurnoides  (species | Trazel | USDA 4+ | IUCN NE | TSO)
            https://www.treesandshrubsonline.org/articles/corylus/corylus-x-colurnoides/
            [habitat] Mountain forests
  4.   0.953  Forsythia koreana  (species | USDA 5+ | IUCN NE | TSO)
            https://www.treesandshrubsonline.org/articles/forsythia/forsythia-koreana/
            [habitat] Mountain forests.
  5.   0.953  Nothofagus × blairii  (species | USDA 8+ | IUCN NE | TSO)
            https://www.treesandshrubsonline.org/articles/nothofagus/nothofagus-x-blairii/
            [habitat] Mountain forests
```

Rovnako funguje ľubovoľné prostredie, napr. dažďový prales (aj zápis „rain forest“):

```
python search.py "habitat:rainforest" -k 3
query: 'habitat:rainforest' -> free=[] fields={'habitat': ['rainforest']} filters={}

49 documents match  (model tfidf, idf classic)
  1.   1.014  Hymenosporum flavum  (species | Australian Native Frangipani, Sweetshade | USDA 9+ | IUCN NE | TSO)
            https://www.treesandshrubsonline.org/articles/hymenosporum/hymenosporum-flavum/
            [habitat] Rain forest and tall, open forest
  2.   0.872  Quercus costaricensis  (species | Roble negro | USDA 9+ | IUCN VU | TSO)
            https://www.treesandshrubsonline.org/articles/quercus/quercus-costaricensis/
            [habitat] Mountain rainforests, 2000–3500 m.
  3.   0.808  Araucaria bidwillii  (species | Bunya Pine | USDA 9-10 | TSO)
            https://www.treesandshrubsonline.org/articles/araucaria/araucaria-bidwillii/
            [habitat] Montane rain forests on deep soils.
```

### Otázka 3: Pri ktorých drevinách sú vošky škodcom?
**Dopyt:** `pest:aphid` – vety o škodcoch z TSO (text článku) aj z gardenie (odrážky „Watch for …“).

```
python search.py "pest:aphid" -k 5
query: 'pest:aphid' -> free=[] fields={'pests': ['aphid']} filters={}

421 documents match  (model tfidf, idf classic)
  1.   0.923  Genista hispanica  (species | Spanish Gorse | USDA 7-9 | TSO + 1 gardenia)
            https://www.treesandshrubsonline.org/articles/genista/genista-hispanica/
            [pests] Virtually disease free but subject to Aphids
  2.   0.923  Genista lydia  (species | Lydian Broom | USDA 4-9 | TSO + 1 gardenia)
            https://www.treesandshrubsonline.org/articles/genista/genista-lydia/
            [pests] Virtually disease free but subject to Aphids
  3.   0.883  Osmanthus fragrans  (species | Fragrant Olive | USDA 7-11 | IUCN NE | TSO + 3 gardenia)
            https://www.treesandshrubsonline.org/articles/osmanthus/osmanthus-fragrans/
            [pests] Keep an eye out for scale and aphids.
  4.   0.828  Vinca major  (species | Greater Periwinkle | USDA 7-9 | TSO + 2 gardenia)
            https://www.treesandshrubsonline.org/articles/vinca/vinca-major/
            [pests] May be subject to aphids or rust.
  5.   0.828  Vinca minor  (species | Lesser Periwinkle | USDA 3-10 | TSO + 5 gardenia)
            https://www.treesandshrubsonline.org/articles/vinca/vinca-minor/
            [pests] May be subject to aphids or rust.
```

Rovnako funguje škodca, ktorý nie je v zozname regexov, napr. cikádky:

```
python search.py "pest:leafhopper" -k 3
query: 'pest:leafhopper' -> free=[] fields={'pests': ['leafhopper']} filters={}

37 documents match  (model tfidf, idf classic)
  1.   1.227  Phlomis italica  (species | Balearic Island Sage, Italian Jerusalem Sage | USDA 9-11 | TSO + 1 gardenia)
            https://www.treesandshrubsonline.org/articles/phlomis/phlomis-italica/
            [pests] Keep an eye out for leafhoppers.
  2.   1.109  Phlomis fruticosa  (species | Jerusalem Sage | USDA 8-10 | TSO + 1 gardenia)
            https://www.treesandshrubsonline.org/articles/phlomis/phlomis-fruticosa/
            [pests] Watch for leafhoppers.
  3.   1.071  Phlomis  (genus | Woolly Jerusalem Sage, Woolly Jerusalem Sage ' 'Pygmy' | USDA 8-11 | TSO + 2 gardenia)
            https://www.treesandshrubsonline.org/articles/phlomis/
            [pests] Keep an eye out for leafhoppers.
```

### Otázka 4: Ktoré dreviny majú USDA Hardiness Zone 5–8?
**Dopyt:** `zone:5-8` – drevina musí prežiť všetky zóny 5 až 8. Zóny sú zlúčené z TSO
(`USDA Hardiness Zone`) a gardenie (riadok Hardiness). Samotné číslo z TSO („4“ = mrazuvzdorná
do zóny 4) má hornú hranicu otvorenú. Najprv presná zhoda 5–8, potom najužšie pokrývajúce rozsahy.

```
python search.py "zone:5-8" -k 5
query: 'zone:5-8' -> free=[] fields={} filters={'zone': '5-8'}

797 documents match  (model tfidf, idf classic)
  1.   0.000  Abies amabilis  (species | Pacific Silver Fir, Lovely Fir | USDA 5-8 | IUCN LC | TSO + 1 gardenia)
            https://www.treesandshrubsonline.org/articles/abies/abies-amabilis/
  2.   0.000  Abies fanjingshanensis  (species | Fan Jing Lengshan, Fanjing Fir | USDA 5-8 | IUCN EN | TSO)
            https://www.treesandshrubsonline.org/articles/abies/abies-fanjingshanensis/
  3.   0.000  Abies × umbellata  (species | Mitsumine Fir, Dimplecone Fir | USDA 5-8 | IUCN DD | TSO)
            https://www.treesandshrubsonline.org/articles/abies/abies-x-umbellata/
  4.   0.000  Acer cissifolium  (species | Vine-leaved Maple, Ivy-leaved Maple | USDA 5-8 | IUCN LC | TSO)
            https://www.treesandshrubsonline.org/articles/acer/acer-cissifolium/
  5.   0.000  Acer leucoderme  (species | Chalk Maple, White-bark Maple | USDA 5-8 | IUCN LC | TSO)
            https://www.treesandshrubsonline.org/articles/acer/acer-leucoderme/
```

### Otázka 5: Pod akým menom je v TSO rastlina, ktorú gardenia predáva ako *Potentilla fruticosa*?
**Dopyt:** `Potentilla fruticosa` – meno je synonymum → karta druhu *Dasiphora fruticosa*.
Synonymá sú zo zoznamu na stránke TSO, z iných mien kultivarov a z vedeckých mien medzi bežnými
menami na gardenii.

```
python search.py "Potentilla fruticosa" -k 3
query: 'Potentilla fruticosa' -> free=['potentilla', 'fruticosa'] fields={} filters={}

'Potentilla fruticosa' is a synonym of Dasiphora fruticosa
==============================================================================
  Dasiphora fruticosa   https://www.treesandshrubsonline.org/articles/dasiphora/dasiphora-fruticosa/
==============================================================================
  Family / genus        Rosaceae / Dasiphora
  Common names          Shrubby Cinquefoil
  Synonyms (TSO)        16: Pentaphylloides fruticosa; Potentilla fruticosa; Dasiphora floribunda; Potentilla floribunda; Potentilla fruticosa subsp. floribunda; Dasiphora fruticosa subsp. floribunda ...
  Synonyms (gardenia)   Potentilla fruticosa 'Lovely Pink'; Potentilla dahurica 'Abbotswood'; Potentilla davurica 'Abbotswood'; Dasiphora fruticosa
  Habitat               In Ireland its best-known occurrence is on the Burren in N.W. Clare, where it grows in damp hollows on the limestone pavement, but is found in a few other localities farther west and also around Lough Corrib in Galway and E. Mayo (Raven and Walters, Mountain Flowers, pp. 104–7; Elkington and Woodell
  Mountain habitat      yes (mountain, urals)
  Morphology            A deciduous shrub up to 3 or 4 ft high, sometimes prostrate or procumbent; bark shreddy, brown or purplish brown when first exposed; young stems hairy; stipules persistent, membranous, acute, sheathing part of the internode above the leaf-insertion. Leaves odd-pinnate, with normally five leaflets, t
  Height (TSO)          0.91-1.22 m
  Life form             shrub, deciduous
  USDA zone (gardenia)  2 - 7, 3 - 7
  Editorial note        The tendency in modern treatments (e.g. Ertter & Reveal 2002) has been to treat Dasiphora fruticosa as a single variable species without further division into infraspecific taxa. This broad concept en
  Exposure              Full Sun, Partial Sun
  Soil                  Chalk, Loam, Sand, Acid, Alkaline, Neutral
  Tolerances            Drought, Deer, Salt, Rabbit, Fire, Erosion
  Attracts              Butterflies
  Toxic to dogs         Not toxic
  gardenia plants       10: Potentilla fruticosa ‘Pink Beauty’ (Shrubby Cinquefoil); Potentilla fruticosa ‘Goldfinger’ (Shrubby Cinquefoil); Potentilla fruticosa Happy Face® White (Shrubby Cinquefoil); Potentilla fruticosa Happy Face® Pink Paradise (Shrubby Cinquefoil); Potentilla fruticosa Happy Face Hearts® (Shrubby Cinquefoil); Potentilla fruticosa Happy Face® Yellow (Shrubby Cinquefoil) ...

49 documents match  (model tfidf, idf classic)
  1.   7.418  Potentilla  (genus | Cinquefoil | USDA 3-7 | TSO + 1 gardenia)
            https://www.treesandshrubsonline.org/articles/potentilla/
            [habitat] Its parentage traces to Potentilla fruticosa (sometimes seen as Dasiphora fruticosa or Potentilla floribunda), a native of Eurasian meadows and North American wilds.
  2.   5.974  Dasiphora fruticosa  (species | Shrubby Cinquefoil | USDA 2-7 | TSO + 10 gardenia)
            https://www.treesandshrubsonline.org/articles/dasiphora/dasiphora-fruticosa/
            [habitat] In Ireland its best-known occurrence is on the Burren in N.W. Clare, where it grows in damp hollows on the limestone pavement, but is found in a few other localities farther west and also around Lough Corrib in Galway...
  3.   2.936  Betula fruticosa  (species | Japanese Bog Birch | TSO)
            https://www.treesandshrubsonline.org/articles/betula/betula-fruticosa/
            [habitat] Betula fruticosa is a shrubby birch found in damp habitats in eastern Asia.
```

### Otázka 6: Ktoré ohrozené dreviny sa dajú kúpiť ako záhradné rastliny?
**Dopyt:** `status:EN,CR source:gardenia` – IUCN status z TSO, dostupnosť = namapovaná stránka gardenie.

```
python search.py "status:EN,CR source:gardenia" -k 5
query: 'status:EN,CR source:gardenia' -> free=[] fields={} filters={'status': 'EN,CR', 'source': 'gardenia'}

16 documents match  (model tfidf, idf classic)
  1.   0.000  Abies fraseri  (species | Fraser Fir, Fraser's Balsam Fir | USDA 4-7 | IUCN EN | TSO + 1 gardenia)
            https://www.treesandshrubsonline.org/articles/abies/abies-fraseri/
  2.   0.000  Abies koreana  (species | Korean Fir, Gu-sang-na-mu | USDA 4-7 | IUCN EN | TSO + 10 gardenia)
            https://www.treesandshrubsonline.org/articles/abies/abies-koreana/
  3.   0.000  Abies pinsapo  (species | Spanish Fir, Sapin d'Espagne | USDA 6-8 | IUCN EN | TSO + 3 gardenia)
            https://www.treesandshrubsonline.org/articles/abies/abies-pinsapo/
  4.   0.000  Acer griseum  (species | Paperbark Maple, Xue pi feng | USDA 4-8 | IUCN EN | TSO + 1 gardenia)
            https://www.treesandshrubsonline.org/articles/acer/acer-griseum/
  5.   0.000  Araucaria angustifolia  (species | Brazilian Monkey-puzzle | USDA 8-11 | IUCN CR | TSO + 1 gardenia)
            https://www.treesandshrubsonline.org/articles/araucaria/araucaria-angustifolia/
```

### Otázka 7: Ktoré ihličnany sú jedovaté pre psov?
**Dopyt:** `taxonomy:conifer toxic:dogs` – typ „Conifers“ a toxicita z gardenie, druh z TSO.

```
python search.py "taxonomy:conifer toxic:dogs" -k 5
query: 'taxonomy:conifer toxic:dogs' -> free=[] fields={'taxonomy': ['conifer']} filters={'toxic': 'dogs'}

3 documents match  (model tfidf, idf classic)
  1.   1.007  Taxus baccata  (species | Common Yew | USDA 6-8 | TSO + 7 gardenia)
            https://www.treesandshrubsonline.org/articles/taxus/taxus-baccata/
            [taxonomy] Conifers Shrubs Trees
  2.   0.860  Taxus canadensis  (species | Canadian Yew | USDA 3-7 | TSO + 1 gardenia)
            https://www.treesandshrubsonline.org/articles/taxus/taxus-canadensis/
            [taxonomy] Conifers Shrubs
  3.   0.860  Taxus × media  (species | Anglo-Japanese Yew 'Hicksii', Hicksii Yew | USDA 4-7 | TSO + 2 gardenia)
            https://www.treesandshrubsonline.org/articles/taxus/taxus-x-media/
            [taxonomy] Conifers Shrubs
```

### Otázka 8: Ktoré horské dreviny znesú tieň?
**Dopyt:** `habitat:mountain exposure:shade` – habitat z TSO, expozícia „Shade“ z gardenie.

```
python search.py "habitat:mountain exposure:shade" -k 5
query: 'habitat:mountain exposure:shade' -> free=[] fields={'habitat': ['mountain'], 'garden': ['shade']} filters={}

254 documents match  (model tfidf, idf classic)
  1.   0.376  Tilia henryana  (species | Henry's Lime, Toothed Chinese Linden | USDA 6-8 | IUCN LC | TSO + 1 gardenia)
            https://www.treesandshrubsonline.org/articles/tilia/tilia-henryana/
            [habitat] Forests, to 1200 m.
  2.   0.314  Styrax obassia  (species | Fragrant Snowbell | USDA 5-8 | IUCN LC | TSO + 1 gardenia)
            https://www.treesandshrubsonline.org/articles/styrax/styrax-obassia/
            [habitat] Wet mountain forests 700–1500 m asl.
  3.   0.296  Clematis alpina  (species | Clematis 'Pamela Jackman' | USDA 3-9 | TSO + 4 gardenia)
            https://www.treesandshrubsonline.org/articles/clematis/clematis-alpina/
            [habitat] Native of N. Europe and N. Asia, also of the mountains of Central and S. Europe; introduced in 1792.
  4.   0.274  Actinidia polygama  (species | Silver Vine | USDA 4-9 | TSO + 1 gardenia)
            https://www.treesandshrubsonline.org/articles/actinidia/actinidia-polygama/
            [habitat] Native of Central Japan, and plentiful in the mountains there.
  5.   0.246  Stewartia pseudocamellia  (species | Common Stewartia, Japanese Stewartia | USDA 4-8 | IUCN NE | TSO + 1 gardenia)
            https://www.treesandshrubsonline.org/articles/stewartia/stewartia-pseudocamellia/
            [habitat] Mixed mountain forests, 175–1450 m asl.
```

### Otázka 9: Ktoré horské stromy vyššie ako 30 m sú vhodné pre zóny 5–8?
**Dopyt:** `habitat:mountain height:30- zone:5-8` – habitat a výška z TSO, zóny zlúčené z oboch stránok.

```
python search.py "habitat:mountain height:30- zone:5-8" -k 5
query: 'habitat:mountain height:30- zone:5-8' -> free=[] fields={'habitat': ['mountain']} filters={'height': '30-', 'zone': '5-8'}

58 documents match  (model tfidf, idf classic)
  1.   0.182  Pinus strobiformis  (species | Southwestern White Pine | USDA 5-9 | TSO + 1 gardenia)
            https://www.treesandshrubsonline.org/articles/pinus/pinus-strobiformis/
            [habitat] Native to the mountains of western Texas, New Mexico, Arizona, and southwestern Colorado and into the mountains to central Mexico.
  2.   0.181  Magnolia obovata  (species | Japanese Big-leaf Magnolia, White Bark Magnolia | USDA 5-8 | IUCN LC | TSO)
            https://www.treesandshrubsonline.org/articles/magnolia/magnolia-obovata/
            [habitat] Moist to mesic forests, 100–1800 m.
  3.   0.154  Quercus × schochiana  (species | USDA 5-9 | TSO)
            https://www.treesandshrubsonline.org/articles/quercus/quercus-x-schochiana/
            [habitat] Bottomlands and poorly drained uplands.
  4.   0.149  Quercus variabilis  (species | Chinese Cork Oak, Oriental Oak | USDA 5+ | IUCN LC | TSO)
            https://www.treesandshrubsonline.org/articles/quercus/quercus-variabilis/
            [habitat] Evergreen and deciduous forests, sometimes forming pure stands; 500 to 3000 m.
  5.   0.146  Liriodendron chinense  (species | Chinese Tulip Tree, 鹅掌楸 (e zhang qiu) | USDA 5-9 | IUCN NT | TSO + 1 gardenia)
            https://www.treesandshrubsonline.org/articles/liriodendron/liriodendron-chinense/
            [habitat] Mixed montane forests, 900–1000 m.
```

---

## 4. Frameworky a knižnice

| knižnica | na čo | prečo |
|---|---|---|
| `requests` | HTTP session s vlastnými hlavičkami a timeoutom | jednoduchá, spoľahlivá; jedna požiadavka naraz stačí (crawl je zámerne pomalý) |
| `urllib.robotparser`, `urllib.parse` | robots.txt, normalizácia URL | štandardná knižnica; robots.txt sa sťahuje s našimi hlavičkami |
| `re` | **všetka** extrakcia z HTML (odkazy, polia, tabuľky) aj z textu | zadanie vyžaduje REGEX; žiadny HTML parser |
| `html`, `json`, `gzip`, `csv` | entity, záznamy JSONL, index, mapovanie | štandardná knižnica |
| `multiprocessing` | paralelná extrakcia (8 procesov) | priečinok je v OneDrive: 1 proces číta ~7 MB/s, 8 procesov ~42 MB/s |
| `tiktoken` | počty tokenov do štatistiky (bonus) | tokenizér modelov OpenAI (`cl100k_base`, `o200k_base`) |
| `unittest` | unit testy | štandardná knižnica, netreba nič inštalovať |

Zámerne **nepoužívam** BeautifulSoup / lxml / Scrapy (extrakcia má byť REGEX, vlastný crawler dáva
plnú kontrolu nad zdvorilosťou) ani Lucene / Elasticsearch / scikit-learn (indexer a idf sú vlastné).

---

## 5. Architektúra crawlovacieho systému

Oba crawlery používajú rovnakú triedu `PoliteSession` z `crawler_config.py`. Každý URL vstúpi do
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
   └──────────────────────────────────────────────────── ulož pages/*.html + manifest.json
```

* **TSO** (`crawl_articles.py`): seed = 26 stránok `/articles/a/` … `/articles/z/`. Z nich sa berú
  odkazy pod `/articles/` najviac do úrovne druhu (`/articles/<rod>/<druh>/`); stiahnuté stránky
  rodov a druhov sa už **nerozbaľujú** (hĺbka 1: zoznam → stránka → koniec).
* **gardenia** (`crawl_gardenia.py`): `/plants/genera` → stránky rodov (aj podrody z bočného panelu)
  → stránky rastlín. Stránka rodu však ukáže len časť rastlín (zvyšok načíta JavaScript z `/refine_by`,
  ktorý robots.txt zakazuje), preto druhý režim číta **sitemap** z robots.txt:
  `sitemap_index.xml` → `plant-sitemap*.xml` → stiahnu sa len chýbajúce rastliny.

---

## 6. Metadáta ukladané pri crawlovaní

**`manifest.json`, `gardenia/manifest.json`** – jeden záznam na uloženú stránku:

| pole | príklad (TSO) | príklad (gardenia) |
|---|---|---|
| `url` | `https://www.treesandshrubsonline.org/articles/abelia/abelia-chinensis/` | `https://www.gardenia.net/plant/mazus-reptans` |
| `kind` | – (z hĺbky URL: rod / druh) | `index`, `genus`, `plant` |
| `source` | – | `sitemap` (rastlina doplnená zo sitemap) |
| `saved_as` | `pages\articles_abelia_abelia-chinensis.html` | `gardenia\pages\plant_mazus-reptans.html` |
| `size_bytes` | `18071` | `256217` |

**`crawl_log.csv`, `gardenia/crawl_log.csv`** – každá požiadavka (aj z cache):

| timestamp | url | status_code | cached | bytes |
|---|---|---|---|---|
| 1791543199.35 | https://www.treesandshrubsonline.org/articles/a/ | 200 | False | 209025 |
| 1791543204.81 | https://www.treesandshrubsonline.org/articles/b/ | 200 | False | 71177 |
| 1792315706.76 | https://www.gardenia.net/plants/genera/abelia | 200 | False | 557862 |

**`cache/`, `gardenia/cache/`** – HTML pod menom `sha256(url).html`; podľa neho crawler pozná, čo
už má. Log slúži na štatistiku a kontrolu zdvorilosti (časové odstupy, chybové kódy).

---

## 7. Hlavičky, timeouty a oneskorenie – odôvodnenie

[`crawler_config.py`, riadky 28–47](https://github.com/tomcer11/vinf/blob/main/crawler_config.py#L28-L47)

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

CACHE_DIR = Path("./cache")   # defaults used by crawl_articles.py
LOG_FILE = Path("./crawl_log.csv")

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

[`crawler_config.py`, riadky 191–240](https://github.com/tomcer11/vinf/blob/main/crawler_config.py#L191-L240)

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

## 8. Kód: extrakcia URL z HTML

TSO – odkaz `<a … href=…>` v úvodzovkách, apostrofoch aj bez nich; ponechajú sa len odkazy na
rody a druhy:

[`crawl_articles.py`, riadky 55–112](https://github.com/tomcer11/vinf/blob/main/crawl_articles.py#L55-L112)

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

[`crawl_gardenia.py`, riadky 80–104](https://github.com/tomcer11/vinf/blob/main/crawl_gardenia.py#L80-L104)

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

[`crawl_gardenia.py`, riadky 231–243](https://github.com/tomcer11/vinf/blob/main/crawl_gardenia.py#L231-L243)

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

## 9. Kód: extrakcia entít z HTML a textu

`extractor.py` – iba modul `re`. **Stránkové** extraktory vyrežú pole z HTML, **textové** nájdu
hodnotu v texte poľa.

### 9.1 Trees and Shrubs Online – regexy a funkcia

[`extractor.py`, riadky 367–393](https://github.com/tomcer11/vinf/blob/main/extractor.py#L367-L393)

```python
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
```

[`extractor.py`, riadky 417–499](https://github.com/tomcer11/vinf/blob/main/extractor.py#L417-L499)

```python
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
```

### 9.2 gardenia.net – tabuľka Requirements a vedecké synonymá

[`extractor.py`, riadky 512–515](https://github.com/tomcer11/vinf/blob/main/extractor.py#L512-L515)

```python
# "Requirements" table; the page has a mobile and a desktop copy, the first is used
GARDENIA_TABLE_RE = re.compile(
    r"<table class=\"right-information-block\">(.*?)</table>", re.DOTALL)
GARDENIA_ROW_RE = re.compile(r"<th>\s*(.*?)\s*</th>\s*<td>\s*(.*?)\s*</td>", re.DOTALL)
```

[`extractor.py`, riadky 528–554](https://github.com/tomcer11/vinf/blob/main/extractor.py#L528-L554)

```python
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

```

### 9.3 Textové extraktory (spoločné)

| čo | regex (skrátene) | príklad → výsledok |
|---|---|---|
| USDA zóny | `\b(\d{1,2})([ab])?(?:\s*(?:–\|-\|to)\s*(\d{1,2})([ab])?)?\b` | `8b-9a` → `{min: 8, max: 9}`; `4` → `{min: 4, max: null}` |
| výška | `(\d+…)(?:\s*(?:–\|-\|to\|or)\s*(?:over \|about )?(\d+…))?(?:\s*\((?:–\|-)\s*(\d+…)\))?\s*(m\|cm\|ft\|feet)\b` | `Tree 30–40(–60) m tall` → 30–60 m; `up to 3 or 4 ft` → 0,91–1,22 m |
| nadmorská výška | `(\d{1,2},\d{3}\|\d{3,5})(?:…)?\s*(m\|ft\|feet)\b(?!\s*(?:high\|tall…))` | `1,300–2,600 m` → 1300–2600 m; `below 5,000 ft` → 1524 m |
| horské prostredie | `\b(mountains?\|montane\|alpine\|tree ?line\|Alps\|Carpathians\|Tatras?\|Himalayas?…)\b` | `High mountains of southern Europe (Alps, Carpathians)` → `mountain: true` |
| vety o habitate | `native (?:of\|to)\|grows? (?:in\|on)\|…\|(?:in\|on\|along) (?:[\w-]+ ){0,3}(?:forests?\|rain ?forests?\|swamps?\|…)` bez viet o záhradách | `It grows in montane rainforest.` ✓, `planted in the woodland garden` ✗ |
| vety o škodcoch | `pests?\|diseases?\|fung(us\|i\|al)\|infest\w*\|insects?\|blights?\|rots?\|watch for\|keep an eye out for…` + 37 vzorov | `Watch for leafhoppers.` ✓ (leafhopper nie je v zozname vzorov) |
| kanonickí škodcovia | 37 vzorov, napr. `aphid: \b(?:woolly )?aphids?\b\|\bgreenfl(?:y\|ies)\b`, `scale insect: \bscale insects?\b…` (nie „seed scales“) | `Watch for adelgids, aphids and conifer red spider mite.` → `adelgid, aphid, spider mite` |
| synonymá TSO | meno bez autorov cez `SCI_NAME_RE`, bez nesprávne použitých (`, not`, `auct.`, `sensu`) | `Picea excelsa (Lam.) Peterm.` → `Picea excelsa` |
| synonymá gardenie | `^[A-Z][a-z]+ (?:×)? [a-z]{3,}…$`, nie anglické slovo (`tree, nut, banana`), iný rod len s latinskou koncovkou | `Carya pecan`, `Juglans illinoensis` ✓; `Sweet pecan`, `Macadamia nut` ✗ |

[`extractor.py`, riadky 295–302](https://github.com/tomcer11/vinf/blob/main/extractor.py#L295-L302)

```python
# any sentence about pests or diseases, also of the ones not in PEST_PATTERNS:
# "Watch for leafhoppers", "Beech scale can be a problem", "infested by ..."
PEST_CONTEXT_RE = re.compile(
    r"\b(?:pests?|diseases?|diseased|fung(?:us|i|al)|infect\w*|infest\w*|pathogens?|pathogenic|"
    r"parasit\w*|insects?|larvae|grubs?|virus(?:es)?|viral|bacteri\w*|blights?|rots?|cankers?|"
    r"mildews?|galls?|watch (?:out )?for|keep an eye (?:out )?for|"
    r"(?:attacked|infested|defoliated|browsed) by)\b",
    re.IGNORECASE)
```

[`extractor.py`, riadky 318–323](https://github.com/tomcer11/vinf/blob/main/extractor.py#L318-L323)

```python
def pest_sentences(text: str) -> list[str]:
    """Every sentence about pests or diseases: the pest:<word> query must find
    any pest, not only the canonical ones of PEST_PATTERNS."""
    found = [s[:MAX_EVIDENCE_CHARS] for s in sentences(text)
             if PEST_CONTEXT_RE.search(s) or PEST_ANY_RE.search(s)]
    return list(dict.fromkeys(found))[:MAX_PEST_SENTENCES]
```

---

## 10. Indexer a index (TF)

`indexer.py` – vlastný invertovaný index bez knižníc. **Dokument** = stránka TSO (druh alebo rod)
spolu s rastlinami z gardenie, ktoré sú na ňu namapované. Každý dokument je rozdelený na polia
a **každé pole má vlastný invertovaný index** `term → [[doc_id, tf], …]` (tf = počet výskytov termu
v poli dokumentu), dĺžky dokumentov (pre BM25) a normy vektorov pre každú metódu idf (pre kosínus).

| pole | obsah | váha |
|---|---|---:|
| `title` | vedecké meno (titulok TSO) | 5 |
| `name` | bežné mená (TSO + gardenia) | 3 |
| `synonyms` | synonymá TSO, iné mená kultivarov, vedecké synonymá z gardenie | 3 |
| `cultivars` | kultivary TSO, názvy rastlín z gardenie | 1 |
| `taxonomy` | čeľaď, rod, typ rastliny z gardenie | 2 |
| `distribution` | rozšírenie (TSO), pôvod (gardenia) | 1,5 |
| `habitat` | habitat + vety o prostredí (oba zdroje) + značka `mountain` | 1,5 |
| `pests` | škodcovia + všetky vety o škodcoch a chorobách (oba zdroje) | 2 |
| `morphology` | opis, životná forma, listy | 1 |
| `garden` | expozícia, pôda, tolerancie, láka, toxicita, popis (gardenia) | 1 |
| `text` | celý článok TSO a kultivary | 0,5 |

**Tokenizer:** malé písmená, bez diakritiky (`Epicéa → epicea`), `×` → `x`, „rain forest“ →
`rainforest`, slová `[a-z0-9]+`, stop slová, stemmer množného čísla (`aphids → aphid`,
`berries → berry`; latinské `-us`, `-is` ostávajú). Rovnaký riadok sa v poli počíta raz
(10 kultivarov s rovnakou vetou nenafúkne tf).

[`indexer.py`, riadky 310–345](https://github.com/tomcer11/vinf/blob/main/indexer.py#L310-L345)

```python
def build(trees_path: Path = TREES_PATH, out_path: Path = INDEX_PATH) -> dict:
    started = time.time()
    docs = []
    postings = {f: defaultdict(list) for f in FIELD_WEIGHTS}
    lengths = {f: [] for f in FIELD_WEIGHTS}
    n_tokens = 0

    with trees_path.open(encoding="utf-8") as f:
        for doc_id, line in enumerate(f):
            doc = json.loads(line)
            docs.append(doc_info(doc_id, doc))
            for field, text in doc_fields(doc).items():
                tokens = tokenize(text)
                n_tokens += len(tokens)
                lengths[field].append(len(tokens))
                for term, tf in Counter(tokens).items():
                    postings[field][term].append([doc_id, tf])

    n_docs = len(docs)
    fields = {}
    for field in FIELD_WEIGHTS:
        field_postings = dict(sorted(postings[field].items()))
        norms = {}
        for method in IDF_METHODS:
            squares = [0.0] * n_docs
            for plist in field_postings.values():
                idf = idf_value(method, n_docs, len(plist))
                for doc_id, tf in plist:
                    squares[doc_id] += (tf_weight(tf) * idf) ** 2
            norms[method] = [round(math.sqrt(s), 6) for s in squares]
        fields[field] = {
            "postings": field_postings,
            "lengths": lengths[field],
            "avg_length": sum(lengths[field]) / max(1, n_docs),
            "norms": norms,
        }
```

**Koľkokrát sa index vytvára:** raz pri každom behu pipeline – `python indexer.py` po extrakcii
a mapovaní (~30 s), uloží sa do `index/index.json.gz`. `search.py` ho pri štarte len načíta (~2 s)
a nemení. Počas vývoja som index staval znova po každej zmene extraktora alebo polí; pri dopyte sa
nič neprepočítava, normy pre všetky metódy idf sú predpočítané.

6643 documents, 3,870,610 tokens (own tokenizer), 6.3 MB index file

| field | terms | postings |
|---|---:|---:|
| title | 4,691 | 12,635 |
| name | 6,974 | 17,605 |
| synonyms | 7,605 | 17,137 |
| cultivars | 10,326 | 23,233 |
| taxonomy | 1,111 | 14,911 |
| distribution | 1,868 | 22,301 |
| habitat | 12,511 | 113,365 |
| pests | 8,128 | 64,567 |
| morphology | 9,765 | 279,201 |
| garden | 16,752 | 370,275 |
| text | 53,428 | 1,100,415 |

---

## 11. Metódy výpočtu idf a ranking

N = počet dokumentov (6643), df = počet dokumentov, ktorých pole obsahuje term.

| metóda | vzorec | vlastnosť |
|---|---|---|
| `classic` | idf = log10(N / df) | term vo všetkých dokumentoch má idf 0 |
| `smooth` | idf = log10(1 + N / df) | nikdy 0, častým slovám dáva väčšiu váhu |
| `probabilistic` | idf = max(0, log10((N − df + 0,5) / (df + 0,5))) | Robertson / Spärck Jones; slová vo viac ako polovici dokumentov majú idf 0 |

[`indexer.py`, riadky 222–231](https://github.com/tomcer11/vinf/blob/main/indexer.py#L222-L231)

```python
def idf_value(method: str, n_docs: int, df: int) -> float:
    if df <= 0:
        return 0.0
    if method == "classic":
        return math.log10(n_docs / df)
    if method == "smooth":
        return math.log10(1 + n_docs / df)
    if method == "probabilistic":
        return max(0.0, math.log10((n_docs - df + 0.5) / (df + 0.5)))
    raise ValueError(f"unknown idf method: {method}")
```

**Ranking** (`--model`):
* **tfidf** – vektorový model: w(t, d) = (1 + log10 tf) · idf(t); skóre = Σ_polia váha_poľa · cos(q, d)
* **bm25** – Okapi BM25 (k1 = 1,2, b = 0,75) so zvolenou idf:
  Σ_t idf(t) · tf · (k1 + 1) / (tf + k1 · (1 − b + b · |d| / avgdl))

---

## 12. Porovnanie metód idf na dopytoch

`--compare` vypíše idf termov (pre voľné slová v poli `text`, kde je df najväčšie) a top 8 pre
každú metódu. Pri zriedkavých slovách (df ≪ N) sú všetky tri metódy skoro rovnaké; rozdiely
spôsobujú časté slová.

**Dopyt 1** – časté slová + jedno zriedkavé:
```
python search.py "tree shrub leaves flowers aphid" --compare -k 8
query: 'tree shrub leaves flowers aphid' -> free=['tree', 'shrub', 'leave', 'flower', 'aphid'] fields={} filters={}

idf of the query terms (N = 6643)
  text:tree              df=2800  classic=0.375  smooth=0.528  probabilistic=0.137
  text:shrub             df=2749  classic=0.383  smooth=0.534  probabilistic=0.151
  text:leave             df=4548  classic=0.165  smooth=0.391  probabilistic=0.000
  text:flower            df=3786  classic=0.244  smooth=0.440  probabilistic=0.000
  text:aphid             df=27    classic=2.391  smooth=2.393  probabilistic=2.381

Top 8 (tfidf, 5805 matching documents)
rank  classic                           smooth                            probabilistic                     
   1  Illicium anisatum                 Illicium anisatum                 Illicium anisatum                 
   2  Erythrostemon gilliesii           Erythrostemon gilliesii           Rhododendron arboreum             
   3  Sorbus americana                  Sorbus americana                  Globularia                        
   4  Rhododendron arboreum             Rhododendron arboreum             Sorbus americana                  
   5  Hibiscus                          Quercus chrysolepis               Amelanchier arborea               
   6  Salix discolor                    Viburnum rufidulum                Sorbus cashmiriana                
   7  Quercus chrysolepis               Prunus virginiana                 Hibiscus                          
   8  Viburnum rufidulum                Euryops                           Erythrostemon gilliesii           
  classic vs smooth: 6/8 documents in common
  classic vs probabilistic: 5/8 documents in common
```
*probabilistic* úplne ignoruje „leaves“ a „flowers“ (sú vo viac ako polovici článkov), rozhoduje
„aphid“. *smooth* naopak dáva častým slovám väčšiu váhu ako *classic*.

**Dopyt 2** – stredne časté slová:
```
python search.py "evergreen tree mountain forest" --compare -k 8
query: 'evergreen tree mountain forest' -> free=['evergreen', 'tree', 'mountain', 'forest'] fields={} filters={}

idf of the query terms (N = 6643)
  text:evergreen         df=1389  classic=0.680  smooth=0.762  probabilistic=0.578
  text:tree              df=2800  classic=0.375  smooth=0.528  probabilistic=0.137
  text:mountain          df=813   classic=0.912  smooth=0.962  probabilistic=0.855
  text:forest            df=771   classic=0.935  smooth=0.983  probabilistic=0.881

Top 8 (tfidf, 4974 matching documents)
rank  classic                           smooth                            probabilistic                     
   1  Rhododendron: The Hybrids / Azal  Rhododendron: The Hybrids / Azal  Rhododendron: The Hybrids / Azal  
   2  Cornus 'Mountain Moon'            Cornus 'Mountain Moon'            Cornus 'Mountain Moon'            
   3  Cornus capitata                   Cornus capitata                   Cornus capitata                   
   4  Rhododendron arboreum             Rhododendron arboreum             Rhododendron arboreum             
   5  Magnolia acuminata                Magnolia acuminata                Magnolia acuminata                
   6  Hydrangea liukiuensis             Dermatophyllum secundiflorum      Hydrangea liukiuensis             
   7  Prunus ilicifolia                 Quercus douglasii                 Prunus ilicifolia                 
   8  Dermatophyllum secundiflorum      Prunus ilicifolia                 Albizia                           
  classic vs smooth: 7/8 documents in common
  classic vs probabilistic: 7/8 documents in common
```
Žiadne slovo nemá df > N/2, takže sa poradia líšia len málo – najviac „tree“, ktorému
*probabilistic* dáva skoro nulovú váhu.

**Dopyt 3** – pole + voľné slová:
```
python search.py "pest:fungus leaves branches" --compare -k 8
query: 'pest:fungus leaves branches' -> free=['leave', 'branch'] fields={'pests': ['fungus']} filters={}

idf of the query terms (N = 6643)
  text:leave             df=4548  classic=0.165  smooth=0.391  probabilistic=0.000
  text:branch            df=1455  classic=0.660  smooth=0.746  probabilistic=0.552
  pests:fungus           df=212   classic=1.496  smooth=1.510  probabilistic=1.481

Top 8 (tfidf, 212 matching documents)
rank  classic                           smooth                            probabilistic                     
   1  Malus domestica                   Malus domestica                   Malus domestica                   
   2  Larix decidua                     Larix decidua                     Larix decidua                     
   3  Larix laricina                    Larix laricina                    Larix laricina                    
   4  Prunus ilicifolia                 Prunus ilicifolia                 Prunus ilicifolia                 
   5  Hamamelis virginiana              Hamamelis virginiana              Hamamelis virginiana              
   6  Ceanothus arboreus                Ceanothus arboreus                Ceanothus arboreus                
   7  Ceanothus 'Puget Blue'            Ceanothus 'Puget Blue'            Ceanothus 'Puget Blue'            
   8  Araucaria angustifolia            Araucaria angustifolia            Ceanothus 'Concha'                
  classic vs smooth: 8/8 documents in common
  classic vs probabilistic: 7/8 documents in common
```
Povinné `pest:fungus` určí množinu výsledkov; idf mení len poradie podľa voľných slov
(„leaves“ má pri *probabilistic* idf 0).

**Dopyt 4** – samé časté slová:
```
python search.py "deciduous tree autumn colour red leaves" --compare -k 8
query: 'deciduous tree autumn colour red leaves' -> free=['deciduous', 'tree', 'autumn', 'colour', 'red', 'leave'] fields={} filters={}

idf of the query terms (N = 6643)
  text:deciduous         df=1210  classic=0.740  smooth=0.812  probabilistic=0.652
  text:tree              df=2800  classic=0.375  smooth=0.528  probabilistic=0.137
  text:autumn            df=976   classic=0.833  smooth=0.892  probabilistic=0.764
  text:colour            df=1154  classic=0.760  smooth=0.830  probabilistic=0.677
  text:red               df=1690  classic=0.594  smooth=0.693  probabilistic=0.467
  text:leave             df=4548  classic=0.165  smooth=0.391  probabilistic=0.000

Top 8 (tfidf, 5561 matching documents)
rank  classic                           smooth                            probabilistic                     
   1  Rhododendron: The Hybrids / Azal  Rhododendron: The Hybrids / Azal  Rhododendron: The Hybrids / Azal  
   2  Weigela Red-Flowered Group        Weigela Red-Flowered Group        Weigela Red-Flowered Group        
   3  Acer × freemanii                  Acer × freemanii                  Acer × freemanii                  
   4  Corylus 'Te Terra Red'            Corylus 'Te Terra Red'            Corylus 'Te Terra Red'            
   5  Quercus Red Flush Group           Quercus Red Flush Group           Quercus Red Flush Group           
   6  Elaeagnus umbellata               Elaeagnus umbellata               Elaeagnus umbellata               
   7  Acer rubrum                       Acer rubrum                       Acer shirasawanum                 
   8  Clematis paniculata               Clematis paniculata               Acer rubrum                       
  classic vs smooth: 8/8 documents in common
  classic vs probabilistic: 7/8 documents in common
```

Rovnaký dopyt s BM25 (saturácia tf) – rozdiely medzi idf sú podobné, poradie iné ako pri TF-IDF:
```
python search.py "tree shrub leaves flowers aphid" --compare -k 8 --model bm25
query: 'tree shrub leaves flowers aphid' -> free=['tree', 'shrub', 'leave', 'flower', 'aphid'] fields={} filters={}

idf of the query terms (N = 6643)
  text:tree              df=2800  classic=0.375  smooth=0.528  probabilistic=0.137
  text:shrub             df=2749  classic=0.383  smooth=0.534  probabilistic=0.151
  text:leave             df=4548  classic=0.165  smooth=0.391  probabilistic=0.000
  text:flower            df=3786  classic=0.244  smooth=0.440  probabilistic=0.000
  text:aphid             df=27    classic=2.391  smooth=2.393  probabilistic=2.381

Top 8 (bm25, 5805 matching documents)
rank  classic                           smooth                            probabilistic                     
   1  Globularia                        Syringa reticulata                Globularia                        
   2  Euryops                           Globularia                        Euryops                           
   3  Syringa reticulata                Euryops                           Dendromecon harfordii             
   4  Dendromecon harfordii             Dendromecon harfordii             Heptacodium miconioides           
   5  Heptacodium miconioides           Arbutus andrachne                 Syringa reticulata                
   6  Arbutus andrachne                 Heptacodium miconioides           Arbutus andrachne                 
   7  Vitex agnus-castus                Lupinus arboreus                  Vitex agnus-castus                
   8  Lupinus arboreus                  Vitex agnus-castus                Ficus                             
  classic vs smooth: 8/8 documents in common
  classic vs probabilistic: 7/8 documents in common
```

---

## 13. Štatistika vycrawlovaných dokumentov

Generuje `python stats.py` (`data/stats.md`, `data/stats.json`).

| | Trees and Shrubs Online | gardenia.net |
|---|---:|---:|
| pages in the manifest | 6643 | 10382 |
| pages per kind | genus 930, species 5713, listing a-z 26 | index 1, genus 489, plant 9892 |
| HTML files saved | 6669 | 10382 |
| relevant for the project | 6643 (genus + species pages; the a-z listings are navigation) | 3230 plant pages mapped to TSO (trees and shrubs) |
| size of the HTML | 247.1 MB | 3,413.5 MB |
| size on disk (4 KiB clusters) | 260.4 MB | 3,434.9 MB |
| average page | 37 kB | 329 kB |
| cache (files / size) | 6669 / 247.1 MB | 10394 / 3,416.3 MB |
| requests in the crawl log (all runs) | 13321 | 38550 |
| of them HTTP 200 / served from cache | 10941 / 2379 | 10431 / 28118 |

**Tokeny (tiktoken) – bonus.** `cl100k_base` (GPT-4), `o200k_base` (GPT-4o), pre surové HTML
aj pre čistý text, ktorý z neho vytiahol extraktor:

| | | characters | cl100k_base | o200k_base |
|---|---|---:|---:|---:|
| Trees and Shrubs Online | raw HTML | 246,740,636 | 85,091,136 | 80,174,377 |
| Trees and Shrubs Online | extracted text | 22,736,465 | 5,935,061 | 5,804,204 |
| gardenia.net | raw HTML | 3,370,295,369 | 1,091,622,269 | 1,085,789,296 |
| gardenia.net | extracted text | 33,513,318 | 7,947,688 | 7,752,796 |

**Vyplnenosť polí po extrakcii:**

**Trees and Shrubs Online**: 6643 records, 33.1 MB JSONL

| field | records | % |
|---|---:|---:|
| family | 6635 | 99.9 |
| common_names | 2027 | 30.5 |
| synonym_names | 2606 | 39.2 |
| description | 3575 | 53.8 |
| editorial_note | 880 | 13.2 |
| distribution | 1931 | 29.1 |
| habitat | 1808 | 27.2 |
| habitat_from_text | 3820 | 57.5 |
| usda | 1386 | 20.9 |
| rhs | 1858 | 28.0 |
| conservation | 1751 | 26.4 |
| height | 4147 | 62.4 |
| altitude | 1731 | 26.1 |
| mountain | 2145 | 32.3 |
| pests | 402 | 6.1 |
| pest_sentences | 633 | 9.5 |
| main_text | 6162 | 92.8 |
| sections | 1800 | 27.1 |

**gardenia.net**: 9892 records, 68.3 MB JSONL

| field | records | % |
|---|---:|---:|
| common_names | 9810 | 99.2 |
| scientific_synonyms | 2733 | 27.6 |
| plant_type | 9892 | 100.0 |
| usda | 9889 | 100.0 |
| height | 9887 | 99.9 |
| exposure | 9892 | 100.0 |
| soil_type | 9836 | 99.4 |
| tolerances | 9565 | 96.7 |
| attracts | 6813 | 68.9 |
| garden_uses | 9417 | 95.2 |
| native_to | 4599 | 46.5 |
| habitat_sentences | 6139 | 62.1 |
| pests | 5922 | 59.9 |
| pest_sentences | 8305 | 84.0 |
| description | 9892 | 100.0 |

---

## 14. Unit testy (bonus)

`tests/test_extractor.py` (unittest, bez ďalších knižníc):

* textové extraktory na krátkych reťazcoch – zóny, výška v m / cm / ft, nadmorská výška, vedecké
  mená, delenie viet, škodcovia (aj ľubovoľní), vety o habitate, synonymá TSO a gardenie, pôvod –
  vrátane prípadov, ktoré nesmú prejsť („seed scales“ nie je škodca, „leaf mold“ nie je choroba,
  „100 ft high“ nie je nadmorská výška, „Sweet pecan“ nie je synonymum),
* **29 reálnych stránok**: 17 z TSO (15 druhov vrátane starých Beanových článkov, stránky
  s redakčnou poznámkou, s dažďovým pralesom, stránky kultivaru a skupiny kultivarov; 2 rody)
  a 12 z gardenie (dreviny, trvalka, kultivary, varieta, hybrid); očakávané hodnoty sú overené v HTML,
* mapovanie gardenia → TSO (kultivar aj podľa jeho iného mena, druh, synonymum TSO aj gardenie,
  nesprávne použité meno, rod len pre dreviny).

```
python -m unittest discover -s tests -v
...
Ran 46 tests
OK
```

---

## 15. Spustenie a ZIP

`odovzdanie.zip` obsahuje kód (`*.py`, `tests/`), tento report a vygenerované `data/stats.*`,
`data/mapping.csv` (bez stiahnutých stránok a cache – 3,7 GB).

```
pip install requests tiktoken
python crawl_articles.py                    # TSO (berie sa z cache)
python crawl_gardenia.py --from-sitemap     # gardenia
python extractor.py                         # data/tso.jsonl, data/gardenia.jsonl
python mapping.py                           # data/trees.jsonl, data/mapping.csv
python indexer.py                           # index/index.json.gz
python stats.py                             # data/stats.md, data/stats.json
python search.py "pest:leafhopper"          # alebo bez argumentu interaktívne
python search.py "tree shrub leaves flowers aphid" --compare
python -m unittest discover -s tests -v
```
