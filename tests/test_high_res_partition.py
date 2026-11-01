import json
import numpy as np
from PIL import Image
from shapely.geometry import shape
from shapely.ops import unary_union
import time
import sys
import os
import re

sys.path.insert(0, ".")

from core.server.EquirectangularRasteriser import EquirectangularRasteriser

rasteriser = EquirectangularRasteriser({'width': 4320, 'height': 2160})

# 1. Load base 10m layers
with open('tests/geo_cache/ne_admin0.geojson', 'r', encoding='utf-8') as f:
  admin0_fc = json.load(f)
with open('tests/geo_cache/ne_admin1.geojson', 'r', encoding='utf-8') as f:
  admin1_fc = json.load(f)
with open('tests/geo_cache/ne_units.geojson', 'r', encoding='utf-8') as f:
  units_fc = json.load(f)

# Index admin1 by country
admin1_by_adm0 = {}
for feat in admin1_fc['features']:
  a0 = feat.get('properties', {}).get('adm0_a3')
  if a0 not in admin1_by_adm0:
    admin1_by_adm0[a0] = []
  admin1_by_adm0[a0].append(feat)

# Base modern entities (except splits: GBR, ITA, IND, IDN, MYS)
entities = []
excluded_a3 = {'GBR', 'IDN', 'IND', 'ITA', 'MYS'}
admin0_by_a3 = {}
for feat in admin0_fc['features']:
  props = feat['properties']
  a3 = props.get('ADM0_A3')
  if a3:
    admin0_by_a3[a3] = feat
  if a3 in excluded_a3:
    continue
  name = props.get('ADMIN') or props.get('NAME')
  k = re.sub(r'[^\w\s-]', '', name.lower()).strip()
  k = re.sub(r'[\s-]+', '_', k)
  idx = rasteriser.A_rasteriseGeometry(shape(feat['geometry']))
  if idx.size > 0:
    entities.append({'entity_id': k, 'flat_indices': idx})

# UK constituents
units_by_gu = {f['properties'].get('GU_A3'): f for f in units_fc['features'] if f['properties'].get('GU_A3')}
for gu, k in [('ENG', 'england'), ('SCT', 'scotland'), ('WLS', 'wales'), ('NIR', 'northern_ireland')]:
  idx = rasteriser.A_rasteriseGeometry(shape(units_by_gu[gu]['geometry']))
  entities.append({'entity_id': k, 'flat_indices': idx})

# Italy: Venice (Veneto + Friuli) and Italy Rest
veneto_names = {'Belluno', 'Padova', 'Rovigo', 'Treviso', 'Venezia', 'Verona', 'Vicenza', 'Udine', 'Gorizia', 'Trieste', 'Pordenone'}
veneto_parts = [shape(f['geometry']) for f in admin1_by_adm0.get('ITA', []) if f.get('properties', {}).get('name') in veneto_names]
veneto_geom = unary_union(veneto_parts)
italy_full = shape(admin0_by_a3['ITA']['geometry'])
italy_rest_geom = italy_full.difference(veneto_geom)
entities.append({'entity_id': 'venice', 'flat_indices': rasteriser.A_rasteriseGeometry(veneto_geom)})
entities.append({'entity_id': 'italy_rest', 'flat_indices': rasteriser.A_rasteriseGeometry(italy_rest_geom)})

# India: Goa and India Rest
goa_parts = [shape(f['geometry']) for f in admin1_by_adm0.get('IND', []) if f.get('properties', {}).get('name') == 'Goa']
goa_geom = unary_union(goa_parts)
india_full = shape(admin0_by_a3['IND']['geometry'])
india_rest_geom = india_full.difference(goa_geom)
entities.append({'entity_id': 'goa', 'flat_indices': rasteriser.A_rasteriseGeometry(goa_geom)})
entities.append({'entity_id': 'india_rest', 'flat_indices': rasteriser.A_rasteriseGeometry(india_rest_geom)})

# Indonesia: Java and Outer Islands
java_names = {'Banten', 'Jakarta Raya', 'Jawa Barat', 'Jawa Tengah', 'Jawa Timur', 'Yogyakarta'}
java_parts = [shape(f['geometry']) for f in admin1_by_adm0.get('IDN', []) if f.get('properties', {}).get('name') in java_names]
java_geom = unary_union(java_parts)
indonesia_full = shape(admin0_by_a3['IDN']['geometry'])
outer_indo_geom = indonesia_full.difference(java_geom)
entities.append({'entity_id': 'java', 'flat_indices': rasteriser.A_rasteriseGeometry(java_geom)})
entities.append({'entity_id': 'indonesia_outer_islands', 'flat_indices': rasteriser.A_rasteriseGeometry(outer_indo_geom)})

# Malaysia: Malaya and Borneo
borneo_my_names = {'Labuan', 'Sabah', 'Sarawak'}
borneo_my_parts = [shape(f['geometry']) for f in admin1_by_adm0.get('MYS', []) if f.get('properties', {}).get('name') in borneo_my_names]
borneo_my_geom = unary_union(borneo_my_parts)
malaysia_full = shape(admin0_by_a3['MYS']['geometry'])
malaya_geom = malaysia_full.difference(borneo_my_geom)
entities.append({'entity_id': 'british_malaya', 'flat_indices': rasteriser.A_rasteriseGeometry(malaya_geom)})
entities.append({'entity_id': 'british_borneo_malaysia', 'flat_indices': rasteriser.A_rasteriseGeometry(borneo_my_geom)})

# 2. Add High-Resolution 10m Historical Entities:
# Brazil 1650: Coastal Captaincies
br_1650_postals = {'PE', 'AL', 'PB', 'RN', 'CE', 'PI', 'MA', 'BA', 'SE', 'ES', 'RJ', 'SP', 'MG', 'PR', 'SC'}
parts_1650 = [shape(f['geometry']) for f in admin1_by_adm0.get('BRA', []) if f.get('properties', {}).get('postal') in br_1650_postals]
entities.append({'entity_id': 'brazil_1650', 'flat_indices': rasteriser.A_rasteriseGeometry(unary_union(parts_1650))})

# Brazil 1800: Brazil excluding Acre
parts_1800 = [shape(f['geometry']) for f in admin1_by_adm0.get('BRA', []) if f.get('properties', {}).get('postal') != 'AC']
entities.append({'entity_id': 'brazil_1800', 'flat_indices': rasteriser.A_rasteriseGeometry(unary_union(parts_1800))})

# USA 1800: East of Mississippi River (excluding FL)
usa_1800_postals = {'ME', 'NH', 'VT', 'MA', 'RI', 'CT', 'NY', 'NJ', 'PA', 'DE', 'MD', 'DC', 'VA', 'WV', 'NC', 'SC', 'GA', 'KY', 'TN', 'OH', 'IN', 'IL', 'MI', 'WI', 'MS', 'AL'}
parts_usa1800 = [shape(f['geometry']) for f in admin1_by_adm0.get('USA', []) if f.get('properties', {}).get('postal') in usa_1800_postals]
entities.append({'entity_id': 'united_states_1800', 'flat_indices': rasteriser.A_rasteriseGeometry(unary_union(parts_usa1800))})

# France 1900: France minus Alsace-Lorraine
al_parts = [shape(f['geometry']) for f in admin1_by_adm0.get('FRA', []) if f.get('properties', {}).get('code_hasc') in ('FR.BR', 'FR.HR', 'FR.MO')]
fra_1900 = shape(admin0_by_a3['FRA']['geometry']).difference(unary_union(al_parts))
entities.append({'entity_id': 'france_1900', 'flat_indices': rasteriser.A_rasteriseGeometry(fra_1900)})

# Bolivia 1900: Modern Bolivia + Acre
acre_part = [shape(f['geometry']) for f in admin1_by_adm0.get('BRA', []) if f.get('properties', {}).get('postal') == 'AC']
bol_1900 = unary_union([shape(admin0_by_a3['BOL']['geometry'])] + acre_part)
entities.append({'entity_id': 'bolivia_1900', 'flat_indices': rasteriser.A_rasteriseGeometry(bol_1900)})

# British Raj 1900: India + Pakistan + Bangladesh + Myanmar
raj_parts = [shape(f['geometry']) for f in admin0_fc['features'] if f['properties'].get('ADM0_A3') in ('IND', 'PAK', 'BGD', 'MMR')]
entities.append({'entity_id': 'india_1900', 'flat_indices': rasteriser.A_rasteriseGeometry(unary_union(raj_parts))})

# Greece 1920: Greece + Eastern Thrace
thrace_parts = [shape(f['geometry']) for f in admin1_by_adm0.get('TUR', []) if f.get('properties', {}).get('code_hasc') in ('TR.ED', 'TR.KL', 'TR.TG')]
gre_1920 = unary_union([shape(admin0_by_a3['GRC']['geometry'])] + thrace_parts)
entities.append({'entity_id': 'greece_1920', 'flat_indices': rasteriser.A_rasteriseGeometry(gre_1920)})

# Russia 1500: Grand Duchy of Moscow
moscow_1500_hasc = {
  'RU.MC', 'RU.MS', 'RU.NG', 'RU.PS', 'RU.TV', 'RU.YS', 'RU.VL', 'RU.IV',
  'RU.KS', 'RU.VG', 'RU.RZ', 'RU.NN', 'RU.TL', 'RU.KG', 'RU.SM', 'RU.BR',
  'RU.AR', 'RU.KO'
}
parts_1500 = [shape(f['geometry']) for f in admin1_by_adm0.get('RUS', []) if f.get('properties', {}).get('code_hasc') in moscow_1500_hasc]
entities.append({'entity_id': 'russia_1500', 'flat_indices': rasteriser.A_rasteriseGeometry(unary_union(parts_1500))})

# Russia 1650: Tsardom of Muscovy (excluding Baltic/Black Sea/Caucasus)
rus_1650_excluded = {'RU.SP', 'RU.LN', 'RU.KI', 'RU.KN', 'RU.DA', 'RU.CN', 'RU.IN', 'RU.KB', 'RU.KC', 'RU.SO', 'RU.AD', 'UA.KR'}
parts_1650 = [shape(f['geometry']) for f in admin1_by_adm0.get('RUS', []) if f.get('properties', {}).get('code_hasc') not in rus_1650_excluded]
entities.append({'entity_id': 'russia_1650', 'flat_indices': rasteriser.A_rasteriseGeometry(unary_union(parts_1650))})

# Russian Empire 1800 & 1900: Russia + Finland + Baltics + Belarus + Ukraine + Moldova + South Caucasus + Central Asia
rus_empire_a3 = {'RUS', 'FIN', 'EST', 'LVA', 'LTU', 'BLR', 'UKR', 'MDA', 'GEO', 'ARM', 'AZE', 'KAZ', 'UZB', 'TKM', 'KGZ', 'TJK'}
rus_empire_parts = [shape(f['geometry']) for f in admin0_fc['features'] if f['properties'].get('ADM0_A3') in rus_empire_a3]
entities.append({'entity_id': 'russia_1800', 'flat_indices': rasteriser.A_rasteriseGeometry(unary_union(rus_empire_parts))})
entities.append({'entity_id': 'russia_1900', 'flat_indices': rasteriser.A_rasteriseGeometry(unary_union(rus_empire_parts))})

# Venice 1500, 1650, 1800: Veneto + Friuli
entities.append({'entity_id': 'venice_1500', 'flat_indices': rasteriser.A_rasteriseGeometry(veneto_geom)})
entities.append({'entity_id': 'venice_1650', 'flat_indices': rasteriser.A_rasteriseGeometry(veneto_geom)})
entities.append({'entity_id': 'venice_1800', 'flat_indices': rasteriser.A_rasteriseGeometry(veneto_geom)})

print(f'Total entities for partition: {len(entities)}')

# Run partition
from core.server.ArealMaskGenerator import ArealMaskGenerator
gen = ArealMaskGenerator()
t0 = time.time()
res = gen.f_partition_equivalence_classes(entities, 'output/areal_masks/provinces_test_clean.png', 104729)
print(f'Partition completed in {time.time()-t0:.2f}s!')
print(f'Atomic provinces: {res["province_count"]}')
print(f'Covered pixels: {res["covered_pixels"]:,}')
