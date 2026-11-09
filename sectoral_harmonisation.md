# Sectoral Harmonisation of Labour Relations

This document details the multi-stage harmonisation of KNAW Global Collaboratory occupational and labour-relation records onto five standard economic sectors.

## 1. Overview

KNAW Global Collaboratory datasets record occupational, institutional, and labour-relation attributes across multiple columns (`[Branch]`, `[Occup]`, `[Position]`, `[Branch_HISCO]`, `[Occup_HISCO]`, `[Labour_rel_01]`, and `[Remark]`). To support cross-regional and cross-epochal analysis across all 98 datasets, every active or inactive population cohort recorded under `Id_pop` (`Type_activity` in `L` or `E`) is resolved into one of five harmonised sectoral categories:

1. **`agriculture`** — Primary sector activities: cultivation, animal husbandry, pastoralism, forestry, fishing, hunting, plantation labour, and agrarian tenancy.
2. **`manufacturing`** — Secondary sector activities: artisan crafts, guilds, mining, quarrying, metallurgy, construction, textiles, utilities, and food/beverage processing.
3. **`services`** — Tertiary sector activities: wholesale and retail trade, transport, storage, public administration, defence, clergy, education, medical care, legal services, finance, and domestic service.
4. **`informal_labour`** — Precarious, casual, and street-based activities: street hawking, itinerant peddling, casual day labour, unspecified/marginalised urban labour, begging, and prostitution.
5. **`not_in_work`** — Inactive population: children, students, retired pensioners, rentiers, affluent elites, prisoners, incapable/disabled persons, and non-working household dependents.

---

## 2. Six-Stage Harmonisation Cascade

Because many KNAW datasets leave `[Branch]` as `"NA"` and encode economic activity in `[Occup]`, `[Position]`, `[Occup_HISCO]`/`[Branch_HISCO]`, or `[Labour_rel_01]`, [`d_harmonise_branch`](file:///f:/Preserves/global-collaboratory/core/server/table_converter.py#L144-L287) in [`core/server/table_converter.py`](file:///f:/Preserves/global-collaboratory/core/server/table_converter.py) evaluates a six-stage priority cascade configured by [`common/sectoral_mapping.json`](file:///f:/Preserves/global-collaboratory/common/sectoral_mapping.json):

1. **Stage 1 — `Branch` Lookup (`branch_map`)**:
   Exact and homoglyph-normalised lookup of `[Branch]` against `branch_map` (2,657 keys). Status-only branch strings mapped to `"unclassified"` fall through to subsequent stages.
2. **Stage 2 — Non-Working Labour Relations (`Labour_rel_01`)**:
   Explicit non-working KNAW labour relation codes (`1` = cannot/not expected to work, `2` = affluent/rentiers, `3` = unemployed, `203`/`108`/`10305` = retired/students/inactive) resolve to `"not in work"` (with the exception of `[Position] == "People who beg"`, which resolves to `"informal labour"`). Evaluating this stage prior to `[Occup]` and `[Position]` prevents non-working infant/child dependents in household-estate datasets (such as Russia 1500–1800, Brazil 1650, and UK 1901) from inheriting the household head's occupation.
3. **Stage 3 — `Occup` Lookup (`occup_map` & `branch_map`)**:
   Exact and homoglyph-normalised lookup of `[Occup]` against `occup_map` (2,110 keys) and `branch_map`, covering English, German, Italian, Spanish, Portuguese, Dutch, and Russian occupational strings.
4. **Stage 4 — `Position` & `Remark` Lookup (`position_map`)**:
   Lookup of `[Position]` against `position_map` (207 keys), resolving Venetian guild/fiscal positions, British census statuses, Dutch occupational positions, and Russian social estates (*sosloviya*: `крестьяне`, `купцы`, `мещане`, `посадские`, `цеховые`, `духовенство`, etc.), followed by explicit non-working or mendicant `[Remark]` annotations.
5. **Stage 5 — HISCO Major & Minor Group Lookup (`hisco_map`)**:
   Evaluates `[Occup_HISCO]` (more granular) followed by `[Branch_HISCO]` against `hisco_map`:
   - Major Groups `0`–`5` (`00`–`59`) and Transport (`971`, `980`–`989`) $\rightarrow$ `services`
   - Major Group `6` (`60`–`69`, `599/622`) $\rightarrow$ `agriculture`
   - Major Groups `7`–`9` (`70`–`97`) $\rightarrow$ `manufacturing`
   - Unspecified/marginal HISCO `999` and `5/6/7/8/9` $\rightarrow$ `informal labour`
6. **Stage 6 — Methodological Census Sector Weights (`dataset_sector_weights` & `labour_rel_map`)**:
   For macro-level labour-relation tables where rows lack `Branch`, `Occup`, `Position`, and `HISCO` (such as Argentina 1900/2000, Belarus 2000, Bihar 1900/2000, Bolivia 1900/2000, Brazil 1650/1800, Deccan 1800/1900, England 1851, India 1900/2000, Netherlands 1900/2000, Russia 1900/2000, and South Africa 2000), `dataset_sector_weights` distributes each labour-relation cohort across sectors using the census proportions documented in the KNAW methodological papers, falling back to `labour_rel_map` when a single-sector code applies.

---

## 3. Deduplication & Year Normalisation

During aggregation in [`f_write_harmonised_json`](file:///f:/Preserves/global-collaboratory/core/server/table_converter.py#L316-L426):
- **Summary & Duplicate Cohort Filtering (`redundant_id_pops`)**: Skips `Total population` / `Working population` summary rows, negative adjustment rows (`Double counted professions`), unallocated header rows where all classification fields and remarks are `"NA"`, and redundant summary `Id_pop` keys in legacy 2011–2019 tables that were deduplicated in the October 2020 IISH/KNAW (`DJ - Oct2020` / `UK1901-abridged`) releases.
- **Year Normalisation**: Resolves range strings (such as `"1778-1779"` and `"1780-1781"` in `England 1800.json`) or sentinel `-1` values to clean 4-digit integer years (`1778`, `1780`).

---

## 4. Data Structure

Both raw and harmonised datasets are serialised into two top-level directories:

### 1. Raw Tabular Maps: [`output/json/raw_tables/`](file:///f:/Preserves/global-collaboratory/output/json/raw_tables/)
Contains the raw JSON for each spreadsheet, formatted as a flat map keyed by `Id_pop` where each entry preserves all original column-cell values:

```json
{
  "65": {
    "Id_pop": 65,
    "Country": "Indonesia",
    "Region": "Java",
    "Year": 1900,
    "Total": 1365327,
    "Type_activity": "L",
    "Branch": "Landowners with buffaloes",
    "Labour_rel_01": 4
  }
}
```

### 2. Sectoral Harmonised Maps: [`output/json/sectoral_harmonised/`](file:///f:/Preserves/global-collaboratory/output/json/sectoral_harmonised/)
Harmonises and aggregates population cohorts into flat key-value pairs formatted as `"<sector>_<year>": number`:

```json
{
  "agriculture_1900": 93279493,
  "informal_labour_1900": 10718992,
  "manufacturing_1900": 18413177,
  "not_in_work_1900": 155401899,
  "services_1900": 18585694
}
```
