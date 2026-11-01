# global-collaboratory

> [!NOTE]
> This is kept out-of-sample for the **NWM** for verification and testing purposes. It is not incorporated into other Confederal models.

**Global Collaboratory on the History of Labour Relations (1500-2000)** (CC-BY-SA-4.0). See the IISH page: https://iisg.amsterdam/en/research/projects/global-collaboratory-on-the-history-of-labour-relations-1500-2000

Confoederatio, including CAD-Preservés, is a separate institution not affiliated with IISH. This repository exists to encode their `.xlsx` spreadsheets as `.json`, with areal masking. Two tabular versions will be produced, one with harmonised sectoral schema (agriculture, manufacturing, services, informal labour, not in work); and the other encoding KNAW's original schema.

These are to be placed in the `/output/` folder. Raw files are placed in `/data/`.

- `/output/areal_masks/` - Areal masks for tabular data (4320x2160 WGS84 Equirectangular, 5-arcminute grid):
  - `provinces.png`: 4320x2160 RGB raster flat map.
  - `country_masks.json`: RGB colour definitions per country.
  - `table_masks.json`: Tabular dataset mappings to country masks.
  - `subadmin_masks.json`: Regional division masks.
  - `city_masks.json`: Major urban coordinates.
- `/output/json/raw_tables/` - Unmodified KNAW tabular records indexed by Id_pop.
- `/output/json/sectoral_harmonised/` - Harmonised sectoral labour accounts.

