## Crawl

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

## Tokens (tiktoken)

| | | characters | cl100k_base | o200k_base |
|---|---|---:|---:|---:|
| Trees and Shrubs Online | raw HTML | 246,740,636 | 85,091,136 | 80,174,377 |
| Trees and Shrubs Online | extracted text | 22,736,465 | 5,935,061 | 5,804,204 |
| gardenia.net | raw HTML | 3,370,295,369 | 1,091,622,269 | 1,085,789,296 |
| gardenia.net | extracted text | 33,513,318 | 7,947,688 | 7,752,796 |

## Extractor

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

## gardenia -> TSO mapping

| level | plants |
|---|---:|
| cultivar | 340 |
| species | 1685 |
| synonym | 173 |
| genus | 1032 |
| none | 6662 |
| **mapped** | **3230** (32.7 %) |

TSO pages with at least one gardenia plant: 1119; woody gardenia plants without a TSO genus: 392

## Index

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
