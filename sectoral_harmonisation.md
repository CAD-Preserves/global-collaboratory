# Sectoral Harmonisation of Labour Relations

This document details the mapping of the KNAW Global Collaboratory `Branch` field onto five harmonised economic sectors.

## 1. Overview

KNAW Global Collaboratory datasets categorise occupational activities within the `[Branch]` column. In order to facilitate cross-regional and cross-epochal analysis, every population group recorded under `Id_pop` is harmonised into one of five standard sectoral categories:

1. **`agriculture`** — Primary sector activities: cultivation, animal husbandry, pastoralism, forestry, fishing, hunting, and agrarian tenancy.
2. **`manufacturing`** — Secondary sector activities: artisan crafts, mining, quarrying, metallurgy, construction, textiles, utilities, and food/beverage processing.
3. **`services`** — Tertiary sector activities: wholesale and retail trade, transport, storage, public administration, defence, education, medical care, legal services, finance, and domestic service.
4. **`informal_labour`** — Precarious, casual, and street-based activities: street hawking, itinerant peddling, day labour, casual urban labour, begging, and prostitution.
5. **`not_in_work`** — Inactive population: children, students, retired pensioners, rentiers, affluent elites, prisoners, incapable/disabled persons, and non-working dependents.

---

## 2. Sectoral Mapping Rules

The harmonisation pipeline uses the configuration in [`common/sectoral_mapping.json`](file:///f:/Preserves/global-collaboratory/common/sectoral_mapping.json) to map all observed branch descriptors.

### Agriculture
Includes all agrarian, primary production, and subsistence activities:
- **English**: Agriculture, Animal Husbandry, Forestry, Fishing, Hunting, Pastoralists, Peasants, Farmers, Farm Laborers, Plantations, Sugar plantations, Tenants, Sharecroppers, Agricultural Dependents.
- **Italian/Venetian**: *Agricoltura*, *Coltivatori*, *Mezzadri*, *Affittuari*, *Boscaioli*, *Tagliaboschi*, *Pesca*, *Caccia*.
- **Historical Classifications**: Russian branches `17_18_19` (Agriculture/Livestock), `20` (Forestry), `21` (Fishing/Hunting).

### Manufacturing
Encompasses transformation of materials, handicrafts, guilds, extraction, and building trades:
- **English**: Manufacturing, Mining, Quarrying, Metallurgy, Smelting, Construction, Garments, Tailors, Textiles, Weavers, Spinners, Carpenters, Blacksmiths, Masons, Shoemakers, Food Processing, Sugar Mills, Printers, Paper Makers.
- **Italian/Venetian Guilds**: *Attività manifatturiere*, *Edilizia*, *Costruzioni*, *Fabbri*, *Falegnami*, *Calzolai*, *Sarti*, *Tessitori*, *Barileri*, *Botteri*, *Boccaleri*, *Bombaseri*, *Calegheri*, *Chiodaroli*, *Cimadori*, *Fenestreri*, *Laneri*, *Mureri*, *Oresi*, *Remeri*, *Sartori*, *Specchieri*, *Tagiapiera*, *Verieri*.
- **Historical Classifications**: Russian industrial branches `22` through `40`.

### Services
Covers commercial distribution, circulation, governance, and institutional/personal services:
- **English**: Trade, Wholesale, Retail, Shopkeepers, Commercial Brokerage, Banking, Insurance, Transport, Railroads, Water Transport, Shipping, Post/Telegraph, Administration, Armed Forces, Police, Courts, Clergy, Education, Health/Medical, Domestic Servants, Hospitality, Hoteliers, Liberal Professions.
- **Italian/Venetian Guilds**: *Commercio*, *Trasporti*, *Banche*, *Pubblica amministrazione*, *Alberghi e trattorie*, *Barbieri*, *Hosti*, *Osti*, *Libreri*, *Senseri*, *Notai*, *Avvocati*, *Medici*, *Chirurghi*, *Speziali*, *Spicieri*, *Bastasi*, *Facchini*, *Gondolieri*.
- **Historical Classifications**: Russian administrative, transport, and trade branches `01`–`13` and `41`–`62`.

### Informal Labour
Covers unregistered, irregular, day-to-day, or marginalised occupations:
- **Peddling and Hawking**: Russian branch `59-Peddling, street hawking`, *Ambulanti*, *Rivenduglioli*, *Strazzaroli* (rag collectors).
- **Casual and Day Labour**: Day labourers, *Giornalieri*, *Braccianti*, Temporary labourers in cities, Occasional workers.
- **Marginal Occupations**: Prostitutes, Russian branch `64-Prostitution`, Beggars, Tramps, *Mendicanti*.

### Not in Work
Encompasses the economically non-active demographic:
- **Age Categories & Dependents**: Infants and children (`1 to 4 years old`, `5 to 9 years old`, `10 to 12 years old`), pupils, students, school attendees, and household youth dependents.
- **Unemployed**: Explicitly unemployed (`Unemployed`, *Sans emploi*, *Disoccupati*).
- **Retired, Rentiers & Elites**: Pensioners, rentiers living on income, *Benestanti*, *Capitalisti*, *Agiati*, *Redditieri*, *Proprietari*, Aristocracy, Nobles.
- **Institutional & Incapable**: Prisoners (*Deprived of freedom*), patients in hospices/hospitals, and incapable/disabled persons (`Labour_rel_01 in (1, 2, 3)`).

---

## 3. Data Structure

Both raw and harmonised datasets are serialized into two top-level directories:

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
Harmonises and squishes labour pools down into flat key-value pairs formatted as `"<sector>_<year>": number`:

```json
{
  "agriculture_1900": 6663902,
  "manufacturing_1900": 544268,
  "not_in_work_1900": 16390138,
  "services_1900": 2057766
}
```
