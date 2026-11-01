import json
import os
import sys
import time
import numpy as np
import requests
from shapely.geometry import shape
from shapely.ops import unary_union

sys.path.append("../br-mitchell")
from core.EquirectangularRasteriser import EquirectangularRasteriser

rasteriser = EquirectangularRasteriser({"width": 4320, "height": 2160})
cache_dir = "tests/geo_cache"
os.makedirs(cache_dir, exist_ok=True)

def get_geojson(name, url):
  p = os.path.join(cache_dir, f"{name}.geojson")
  if os.path.exists(p):
    with open(p, "r", encoding="utf-8") as f:
      return json.load(f)
  print(f"Downloading {name}...")
  r = requests.get(url, timeout=30)
  with open(p, "wb") as f:
    f.write(r.content)
  return r.json()

# Base layers
admin0_fc = get_geojson("ne_admin0", "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson")
units_fc = get_geojson("ne_units", "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_map_units.geojson")
admin1_fc = get_geojson("ne_admin1", "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson")

# Historical layers
w1500 = get_geojson("world_1500", "https://raw.githubusercontent.com/aourednik/historical-basemaps/master/geojson/world_1500.geojson")
w1650 = get_geojson("world_1650", "https://raw.githubusercontent.com/aourednik/historical-basemaps/master/geojson/world_1650.geojson")
w1800 = get_geojson("world_1800", "https://raw.githubusercontent.com/aourednik/historical-basemaps/master/geojson/world_1800.geojson")
w1900 = get_geojson("world_1900", "https://raw.githubusercontent.com/aourednik/historical-basemaps/master/geojson/world_1900.geojson")
w1920 = get_geojson("world_1920", "https://raw.githubusercontent.com/aourednik/historical-basemaps/master/geojson/world_1920.geojson")

def extract_named(fc, names):
  parts = []
  for f in fc["features"]:
    props = f.get("properties", {})
    name = props.get("NAME") or props.get("name")
    if name in names:
      parts.append(shape(f["geometry"]))
  return unary_union(parts) if parts else None

# Collect all entities
entities = []

# 1. Base modern entities from admin0 (except GBR, ITA, IND, IDN, MYS)
excluded_a3 = {"GBR", "IDN", "IND", "ITA", "MYS"}
for f in admin0_fc["features"]:
  props = f["properties"]
  a3 = props.get("ADM0_A3")
  if a3 in excluded_a3:
    continue
  name = props.get("ADMIN") or props.get("NAME")
  import re
  k = re.sub(r"[^\w\s-]", "", name.lower()).strip()
  k = re.sub(r"[\s-]+", "_", k)
  idx = rasteriser.A_rasteriseGeometry(shape(f["geometry"]))
  if idx.size > 0:
    entities.append({"entity_id": k, "flat_indices": idx})

# 2. Modern UK constituents
units_by_gu = {f["properties"].get("GU_A3"): f for f in units_fc["features"] if f["properties"].get("GU_A3")}
for gu, k in [("ENG", "england"), ("SCT", "scotland"), ("WLS", "wales"), ("NIR", "northern_ireland")]:
  idx = rasteriser.A_rasteriseGeometry(shape(units_by_gu[gu]["geometry"]))
  entities.append({"entity_id": k, "flat_indices": idx})

# 3. Modern Italy Rest and Veneto
veneto_names = {"Belluno", "Padova", "Rovigo", "Treviso", "Venezia", "Verona", "Vicenza"}
veneto_parts = [shape(f["geometry"]) for f in admin1_fc["features"] if f.get("properties", {}).get("adm0_a3") == "ITA" and f.get("properties", {}).get("name") in veneto_names]
veneto_geom = unary_union(veneto_parts)
for f in admin0_fc["features"]:
  if f["properties"].get("ADM0_A3") == "ITA":
    italy_full = shape(f["geometry"])
    break
italy_rest_geom = italy_full.difference(veneto_geom)
entities.append({"entity_id": "veneto", "flat_indices": rasteriser.A_rasteriseGeometry(veneto_geom)})
entities.append({"entity_id": "italy_rest", "flat_indices": rasteriser.A_rasteriseGeometry(italy_rest_geom)})

# 4. Modern India Rest and Goa
goa_parts = [shape(f["geometry"]) for f in admin1_fc["features"] if f.get("properties", {}).get("adm0_a3") == "IND" and f.get("properties", {}).get("name") == "Goa"]
goa_geom = unary_union(goa_parts)
for f in admin0_fc["features"]:
  if f["properties"].get("ADM0_A3") == "IND":
    india_full = shape(f["geometry"])
    break
india_rest_geom = india_full.difference(goa_geom)
entities.append({"entity_id": "goa", "flat_indices": rasteriser.A_rasteriseGeometry(goa_geom)})
entities.append({"entity_id": "india_rest", "flat_indices": rasteriser.A_rasteriseGeometry(india_rest_geom)})

# 5. Modern Indonesia Java and Outer
java_names = {"Banten", "Jakarta Raya", "Jawa Barat", "Jawa Tengah", "Jawa Timur", "Yogyakarta"}
java_parts = [shape(f["geometry"]) for f in admin1_fc["features"] if f.get("properties", {}).get("adm0_a3") == "IDN" and f.get("properties", {}).get("name") in java_names]
java_geom = unary_union(java_parts)
for f in admin0_fc["features"]:
  if f["properties"].get("ADM0_A3") == "IDN":
    indonesia_full = shape(f["geometry"])
    break
outer_indo_geom = indonesia_full.difference(java_geom)
entities.append({"entity_id": "java", "flat_indices": rasteriser.A_rasteriseGeometry(java_geom)})
entities.append({"entity_id": "indonesia_outer_islands", "flat_indices": rasteriser.A_rasteriseGeometry(outer_indo_geom)})

# 6. Modern Malaysia: Malaya and Borneo MY
for f in admin0_fc["features"]:
  if f["properties"].get("ADM0_A3") == "MYS":
    malaysia_full = shape(f["geometry"])
    break
borneo_my_names = {"Labuan", "Sabah", "Sarawak"}
borneo_my_parts = [shape(f["geometry"]) for f in admin1_fc["features"] if f.get("properties", {}).get("adm0_a3") == "MYS" and f.get("properties", {}).get("name") in borneo_my_names]
borneo_my_geom = unary_union(borneo_my_parts)
malaya_geom = malaysia_full.difference(borneo_my_geom)
entities.append({"entity_id": "british_malaya", "flat_indices": rasteriser.A_rasteriseGeometry(malaya_geom)})
entities.append({"entity_id": "british_borneo_malaysia", "flat_indices": rasteriser.A_rasteriseGeometry(borneo_my_geom)})

# 7. HISTORICAL ENTITIES:
# Brazil 1650: Portuguese Brazil + Dutch Brazil
b1650_geom = extract_named(w1650, ["Portuguese Brazil", "Dutch Brazil"])
if b1650_geom:
  # Clip to modern Brazil land to avoid ocean bleed
  idx_1650 = np.intersect1d(rasteriser.A_rasteriseGeometry(b1650_geom), [e["flat_indices"] for e in entities if e["entity_id"] == "brazil"][0])
  entities.append({"entity_id": "brazil_1650", "flat_indices": idx_1650})

# Brazil 1800: Viceroyalty of Brazil
b1800_geom = extract_named(w1800, ["Viceroyalty of Brazil"])
if b1800_geom:
  idx_1800 = np.intersect1d(rasteriser.A_rasteriseGeometry(b1800_geom), [e["flat_indices"] for e in entities if e["entity_id"] == "brazil"][0])
  entities.append({"entity_id": "brazil_1800", "flat_indices": idx_1800})

# USA 1800: United States of America 1800
usa1800_geom = extract_named(w1800, ["United States of America"])
if usa1800_geom:
  idx_usa1800 = np.intersect1d(rasteriser.A_rasteriseGeometry(usa1800_geom), [e["flat_indices"] for e in entities if e["entity_id"] == "united_states_of_america"][0])
  entities.append({"entity_id": "united_states_1800", "flat_indices": idx_usa1800})

# Russia 1500: Grand Duchy of Moscow
rus1500_geom = extract_named(w1500, ["Grand Duchy of Moscow"])
if rus1500_geom:
  entities.append({"entity_id": "russia_1500", "flat_indices": rasteriser.A_rasteriseGeometry(rus1500_geom)})

# Russia 1650: Tsardom of Muscovy
rus1650_geom = extract_named(w1650, ["Tsardom of Muscovy"])
if rus1650_geom:
  entities.append({"entity_id": "russia_1650", "flat_indices": rasteriser.A_rasteriseGeometry(rus1650_geom)})

# Russia 1800: Russian Empire 1800
rus1800_geom = extract_named(w1800, ["Russian Empire"])
if rus1800_geom:
  entities.append({"entity_id": "russia_1800", "flat_indices": rasteriser.A_rasteriseGeometry(rus1800_geom)})

# Russia 1900: Russian Empire 1900
rus1900_geom = extract_named(w1900, ["Russian Empire"])
if rus1900_geom:
  entities.append({"entity_id": "russia_1900", "flat_indices": rasteriser.A_rasteriseGeometry(rus1900_geom)})

# Venice 1500, 1650, 1800
v1500_geom = extract_named(w1500, ["Venice"])
if v1500_geom:
  entities.append({"entity_id": "venice_1500", "flat_indices": rasteriser.A_rasteriseGeometry(v1500_geom)})
v1650_geom = extract_named(w1650, ["Venice"])
if v1650_geom:
  entities.append({"entity_id": "venice_1650", "flat_indices": rasteriser.A_rasteriseGeometry(v1650_geom)})
v1800_geom = extract_named(w1800, ["Venetia"])
if v1800_geom:
  entities.append({"entity_id": "venice_1800", "flat_indices": rasteriser.A_rasteriseGeometry(v1800_geom)})

# Bolivia 1900
bol1900_geom = extract_named(w1900, ["Bolivia"])
if bol1900_geom:
  entities.append({"entity_id": "bolivia_1900", "flat_indices": rasteriser.A_rasteriseGeometry(bol1900_geom)})

# India 1900 (British Raj)
raj1900_geom = extract_named(w1900, ["British Raj"])
if raj1900_geom:
  entities.append({"entity_id": "india_1900", "flat_indices": rasteriser.A_rasteriseGeometry(raj1900_geom)})

print(f"Total entities assembled: {len(entities)}")

# Now run partitionEquivalenceClasses
sys.path.append("../br-mitchell")
from core.ProvinceMapSynthesizer import ProvinceMapSynthesizer
synth = ProvinceMapSynthesizer(".", {}, rasteriser)

t0 = time.time()
res = synth.partitionEquivalenceClasses(entities, "output/areal_masks/test_provinces.png", 104729)
print(f"Partition completed in {time.time()-t0:.2f}s!")
print(f"Atomic provinces (unique colors): {res['province_count']}")

masks = res["entity_rgb_masks"]
print("brazil_1650 colours:", len(masks.get("brazil_1650", [])))
print("brazil_1800 colours:", len(masks.get("brazil_1800", [])))
print("brazil (modern) colours:", len(masks.get("brazil", [])))
print("united_states_1800 colours:", len(masks.get("united_states_1800", [])))
print("united_states_of_america colours:", len(masks.get("united_states_of_america", [])))
print("russia_1500 colours:", len(masks.get("russia_1500", [])))
print("russia_1650 colours:", len(masks.get("russia_1650", [])))
print("russia_1800 colours:", len(masks.get("russia_1800", [])))
print("russia_1900 colours:", len(masks.get("russia_1900", [])))
print("russia (modern) colours:", len(masks.get("russia", [])))
print("venice_1500 colours:", len(masks.get("venice_1500", [])))

