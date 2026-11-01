import json
import os
import sys
import numpy as np
from shapely.geometry import shape
from shapely.ops import unary_union

sys.path.append("../br-mitchell")
from core.EquirectangularRasteriser import EquirectangularRasteriser

rasteriser = EquirectangularRasteriser({"width": 4320, "height": 2160})

# 1. Modern Brazil from ne_admin0
with open("tests/geo_cache/ne_admin0.geojson", "r", encoding="utf-8") as f:
  admin0 = json.load(f)
brazil_modern_geom = None
for feat in admin0["features"]:
  if feat["properties"].get("ADM0_A3") == "BRA":
    brazil_modern_geom = shape(feat["geometry"])
    break

# 2. Brazil 1650 from world_1650.geojson
import requests
w1650 = requests.get("https://raw.githubusercontent.com/aourednik/historical-basemaps/master/geojson/world_1650.geojson").json()
b1650_parts = []
for feat in w1650["features"]:
  name = feat.get("properties", {}).get("NAME")
  if name in ["Portuguese Brazil", "Dutch Brazil"]:
    b1650_parts.append(shape(feat["geometry"]))
brazil_1650_geom = unary_union(b1650_parts)

# 3. Brazil 1800 from world_1800.geojson
w1800 = requests.get("https://raw.githubusercontent.com/aourednik/historical-basemaps/master/geojson/world_1800.geojson").json()
brazil_1800_geom = None
for feat in w1800["features"]:
  name = feat.get("properties", {}).get("NAME")
  if name == "Viceroyalty of Brazil":
    brazil_1800_geom = shape(feat["geometry"])
    break

print("Brazil Modern geom bounds:", brazil_modern_geom.bounds, "area:", brazil_modern_geom.area)
print("Brazil 1650 geom bounds:", brazil_1650_geom.bounds, "area:", brazil_1650_geom.area)
print("Brazil 1800 geom bounds:", brazil_1800_geom.bounds, "area:", brazil_1800_geom.area)

px_mod = rasteriser.A_rasteriseGeometry(brazil_modern_geom)
px_1650 = rasteriser.A_rasteriseGeometry(brazil_1650_geom)
px_1800 = rasteriser.A_rasteriseGeometry(brazil_1800_geom)

# Clip 1650 and 1800 to modern land boundary to avoid ocean bleed
px_1650_clipped = np.intersect1d(px_1650, px_mod)
px_1800_clipped = np.intersect1d(px_1800, px_mod)

print(f"Pixels - Modern: {len(px_mod)}, 1800: {len(px_1800_clipped)}, 1650: {len(px_1650_clipped)}")

