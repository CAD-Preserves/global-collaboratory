"""Areal Mask Generator Module.

Synthesises 4320x2160 WGS84 Equirectangular areal masks for top-level countries and historical regions.
Produces provinces.png, country_masks.json, table_masks.json, subadmin_masks.json, and city_masks.json.
Uses F:/scrapes/phersu/geojson for authoritative historical territory definitions.
"""

import json
import os
from pathlib import Path
import re
import sys
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import numpy as np
from PIL import Image
import pyjson5
import requests
from shapely.geometry import box, shape
from shapely.ops import unary_union

from core.server.EquirectangularRasteriser import EquirectangularRasteriser


class ArealMaskGenerator:
  """Orchestrator for synthesising WGS84 Equirectangular areal masks with historical border support."""

  def __init__ (self, arg1_root_dir=None, arg2_options=None):
    """Initialises ArealMaskGenerator with workspace root directory and options.

    @param {str|None} [arg1_root_dir=None] - Repository root directory path.
    @param {dict|None} [arg2_options=None] - Optional configuration overrides.
    """
    # Convert from parameters
    let_root_dir = arg1_root_dir
    let_options = arg2_options if isinstance(arg2_options, dict) else {}

    # Declare local instance variables
    let_config_path = ""
    let_default_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    self.root_dir = os.path.abspath(let_root_dir) if let_root_dir else let_default_root
    let_config_path = os.path.join(self.root_dir, "common", "areal_masks", "areal_mask_config.json5")

    with open(let_config_path, "r", encoding="utf-8") as let_file_stream:
      self.config_obj = pyjson5.decode(let_file_stream.read())

    self.cache_dir = os.path.join(self.root_dir, self.config_obj.get("paths", {}).get("cache_dir", "tests/geo_cache"))
    self.data_dir = os.path.join(self.root_dir, self.config_obj.get("paths", {}).get("data_dir", "data"))
    self.input_json_dir = os.path.join(self.root_dir, self.config_obj.get("paths", {}).get("input_json_dir", "output/json"))
    self.output_dir = os.path.join(self.root_dir, self.config_obj.get("paths", {}).get("output_dir", "output/areal_masks"))
    self.outputs_cfg = self.config_obj.get("outputs", {})
    self.phersu_dir = os.path.abspath(self.config_obj.get("paths", {}).get("phersu_dir", "F:/scrapes/phersu/geojson"))
    self.rasteriser = EquirectangularRasteriser(self.config_obj.get("grid", {}))

    os.makedirs(self.cache_dir, exist_ok=True)
    os.makedirs(self.output_dir, exist_ok=True)


  def a_fetch_or_load_layer (self, arg1_layer_name):
    """Fetches or loads a GeoJSON layer from local disk cache or online source.

    @param {str} arg1_layer_name - Name of layer key in sources config.
    @return {dict} Parsed GeoJSON FeatureCollection dictionary.
    """
    # Convert from parameters
    let_layer_name = str(arg1_layer_name or "").strip()

    # Declare local instance variables
    let_cache_path = os.path.join(self.cache_dir, f"{let_layer_name}.geojson")
    let_response = None
    let_sources = self.config_obj.get("sources", {})
    let_url = str(let_sources.get(let_layer_name, "")).strip()

    # Guard clause
    if os.path.exists(let_cache_path):
      with open(let_cache_path, "r", encoding="utf-8") as let_file_stream:
        # Return statement
        return json.load(let_file_stream)

    if not let_url:
      print(f"Error: No URL configured for geospatial layer: {let_layer_name}")
      # Return statement
      return {"features": [], "type": "FeatureCollection"}

    # Function body
    print(f"Downloading {let_layer_name} from {let_url}...")
    let_response = requests.get(let_url, timeout=60)
    with open(let_cache_path, "wb") as let_file_stream:
      let_file_stream.write(let_response.content)

    # Return statement
    return let_response.json()


  def b_extract_phersu_geom (self, arg1_file_name, arg2_target_states, arg3_clip_box=None):
    """Extracts and unions geometries of matching states from a Phersu historical GeoJSON file.

    @param {str} arg1_file_name - Phersu GeoJSON filename (e.g. '1650.01.01.json').
    @param {list} arg2_target_states - List of state names to extract.
    @param {shapely.geometry.box|None} [arg3_clip_box=None] - Optional bounding box for spatial filtering.
    @return {shapely.geometry.base.BaseGeometry|None} Unioned geometry or None.
    """
    # Convert from parameters
    let_clip_box = arg3_clip_box
    let_file_name = str(arg1_file_name or "").strip()
    let_target_states = set(arg2_target_states) if arg2_target_states else set()

    # Declare local instance variables
    let_file_path = os.path.join(self.phersu_dir, let_file_name)
    let_geom = None
    let_parts = []
    let_state_name = ""

    # Guard clause
    if not os.path.exists(let_file_path):
      print(f"Warning: Phersu file not found at {let_file_path}")
      # Return statement
      return None

    # Function body
    with open(let_file_path, "r", encoding="utf-8") as let_file_stream:
      let_fc = json.load(let_file_stream)

    for feature in let_fc.get("features", []):
      let_state_name = feature.get("properties", {}).get("state", "").replace("\n", " ").strip()
      if let_state_name in let_target_states:
        let_geom = shape(feature["geometry"])
        if let_clip_box:
          let_geom = let_geom.intersection(let_clip_box)
        if not let_geom.is_empty:
          let_parts.append(let_geom)

    # Guard clause
    if not let_parts:
      # Return statement
      return None

    # Return statement
    return unary_union(let_parts)


  def c_build_base_entities (self):
    """Constructs modern sovereign entities and constituent country splits.

    Includes UK constituents, Italy (Venice/Veneto vs Rest), India (Goa vs Rest),
    Indonesia (Java vs Outer), and Malaysia (Malaya vs Borneo).

    @return {list} List of entity dictionaries with 'entity_id' and 'flat_indices'.
    """
    # Declare local instance variables
    let_admin0_by_a3 = {}
    let_admin0_fc = self.a_fetch_or_load_layer("ne_admin0")
    let_admin1_fc = self.a_fetch_or_load_layer("ne_admin1")
    let_borneo_my_geom = None
    let_borneo_my_names = {"Labuan", "Sabah", "Sarawak"}
    let_borneo_my_parts = []
    let_entities_array = []
    let_excluded_a3 = {"GBR", "IDN", "IND", "ITA", "MYS"}
    let_goa_geom = None
    let_goa_parts = []
    let_india_full = None
    let_india_rest_geom = None
    let_indonesia_full = None
    let_italy_full = None
    let_italy_rest_geom = None
    let_java_geom = None
    let_java_names = {"Banten", "Jakarta Raya", "Jawa Barat", "Jawa Tengah", "Jawa Timur", "Yogyakarta"}
    let_java_parts = []
    let_malaya_geom = None
    let_malaysia_full = None
    let_outer_indo_geom = None
    let_units_by_gu = {}
    let_units_fc = self.a_fetch_or_load_layer("ne_units")
    let_veneto_geom = None
    let_veneto_names = {"Belluno", "Padova", "Rovigo", "Treviso", "Venezia", "Verona", "Vicenza"}
    let_veneto_parts = []

    # Function body
    for feature in let_admin0_fc.get("features", []):
      let_a3 = feature.get("properties", {}).get("ADM0_A3")
      if let_a3:
        let_admin0_by_a3[let_a3] = feature

    for feature in let_units_fc.get("features", []):
      let_gu = feature.get("properties", {}).get("GU_A3")
      if let_gu:
        let_units_by_gu[let_gu] = feature

    # 1. Base sovereign countries from Natural Earth admin 0
    for feature in let_admin0_fc.get("features", []):
      let_props = feature.get("properties", {})
      let_a3 = let_props.get("ADM0_A3")
      if let_a3 in let_excluded_a3:
        continue
      let_name = let_props.get("ADMIN") or let_props.get("NAME")
      let_key = self.to_snake_key(let_name)
      let_indices = self.rasteriser.A_rasteriseGeometry(shape(feature["geometry"]))
      if let_indices.size > 0:
        let_entities_array.append({"entity_id": let_key, "flat_indices": let_indices})

    # 2. Partition United Kingdom into England, Scotland, Wales, Northern Ireland
    for gu_code, constituent_key in [("ENG", "england"), ("SCT", "scotland"), ("WLS", "wales"), ("NIR", "northern_ireland")]:
      if gu_code in let_units_by_gu:
        let_indices = self.rasteriser.A_rasteriseGeometry(shape(let_units_by_gu[gu_code]["geometry"]))
        let_entities_array.append({"entity_id": constituent_key, "flat_indices": let_indices})

    # 3. Partition Italy into Venice (Veneto) and Rest of Italy
    if "ITA" in let_admin0_by_a3:
      let_italy_full = shape(let_admin0_by_a3["ITA"]["geometry"])
      for feature in let_admin1_fc.get("features", []):
        if feature.get("properties", {}).get("adm0_a3") == "ITA" and feature.get("properties", {}).get("name") in let_veneto_names:
          let_veneto_parts.append(shape(feature["geometry"]))
      let_veneto_geom = unary_union(let_veneto_parts)
      let_italy_rest_geom = let_italy_full.difference(let_veneto_geom)
      let_entities_array.append({"entity_id": "venice", "flat_indices": self.rasteriser.A_rasteriseGeometry(let_veneto_geom)})
      let_entities_array.append({"entity_id": "italy_rest", "flat_indices": self.rasteriser.A_rasteriseGeometry(let_italy_rest_geom)})

    # 4. Partition India into Goa and Rest of India
    if "IND" in let_admin0_by_a3:
      let_india_full = shape(let_admin0_by_a3["IND"]["geometry"])
      for feature in let_admin1_fc.get("features", []):
        if feature.get("properties", {}).get("adm0_a3") == "IND" and feature.get("properties", {}).get("name") == "Goa":
          let_goa_parts.append(shape(feature["geometry"]))
      let_goa_geom = unary_union(let_goa_parts)
      let_india_rest_geom = let_india_full.difference(let_goa_geom)
      let_entities_array.append({"entity_id": "goa", "flat_indices": self.rasteriser.A_rasteriseGeometry(let_goa_geom)})
      let_entities_array.append({"entity_id": "india_rest", "flat_indices": self.rasteriser.A_rasteriseGeometry(let_india_rest_geom)})

    # 5. Partition Indonesia into Java and Outer Islands
    if "IDN" in let_admin0_by_a3:
      let_indonesia_full = shape(let_admin0_by_a3["IDN"]["geometry"])
      for feature in let_admin1_fc.get("features", []):
        if feature.get("properties", {}).get("adm0_a3") == "IDN" and feature.get("properties", {}).get("name") in let_java_names:
          let_java_parts.append(shape(feature["geometry"]))
      let_java_geom = unary_union(let_java_parts)
      let_outer_indo_geom = let_indonesia_full.difference(let_java_geom)
      let_entities_array.append({"entity_id": "java", "flat_indices": self.rasteriser.A_rasteriseGeometry(let_java_geom)})
      let_entities_array.append({"entity_id": "indonesia_outer_islands", "flat_indices": self.rasteriser.A_rasteriseGeometry(let_outer_indo_geom)})

    # 6. Partition Malaysia into British Malaya and British Borneo
    if "MYS" in let_admin0_by_a3:
      let_malaysia_full = shape(let_admin0_by_a3["MYS"]["geometry"])
      for feature in let_admin1_fc.get("features", []):
        if feature.get("properties", {}).get("adm0_a3") == "MYS" and feature.get("properties", {}).get("name") in let_borneo_my_names:
          let_borneo_my_parts.append(shape(feature["geometry"]))
      let_borneo_my_geom = unary_union(let_borneo_my_parts)
      let_malaya_geom = let_malaysia_full.difference(let_borneo_my_geom)
      let_entities_array.append({"entity_id": "british_malaya", "flat_indices": self.rasteriser.A_rasteriseGeometry(let_malaya_geom)})
      let_entities_array.append({"entity_id": "british_borneo_malaysia", "flat_indices": self.rasteriser.A_rasteriseGeometry(let_borneo_my_geom)})

    # Return statement
    return let_entities_array


  def d_build_historical_entities (self, arg1_base_entities_array):
    """Extracts and rasterises historical geometries directly from F:/scrapes/phersu/geojson.

    Captures Brazil 1650 (coastal captaincies), Brazil 1800 (viceroyalty),
    USA 1800 (16 states + NW/SW territories), France 1900 (Third Republic),
    Bolivia 1900, British India 1900, Greece 1920 (Treaty of Sevres),
    Russia 1500 (Moscow), Russia 1650 (Muscovy), Russian Empire 1800/1900, and Venice.

    @param {list} arg1_base_entities_array - Base modern entities list.
    @return {list} List of historical entity dictionaries.
    """
    # Convert from parameters
    let_base_entities = arg1_base_entities_array if isinstance(arg1_base_entities_array, list) else []

    # Declare local instance variables
    let_b1650_geom = None
    let_b1800_geom = None
    let_bol1900_geom = None
    let_brazil_modern_idx = np.zeros(0, dtype=np.int32)
    let_fra1900_geom = None
    let_france_modern_idx = np.zeros(0, dtype=np.int32)
    let_gre1920_geom = None
    let_historical_entities = []
    let_india_box = box(60, 5, 100, 38)
    let_master_land_idx = np.zeros(0, dtype=np.int32)
    let_raj_parts = []
    let_rus1500_geom = None
    let_rus1650_geom = None
    let_rus1800_geom = None
    let_rus1900_geom = None
    let_sa_box = box(-80, -35, -30, 10)
    let_usa1800_geom = None
    let_usa_modern_idx = np.zeros(0, dtype=np.int32)
    let_v1500_geom = None
    let_v1650_geom = None

    # Function body
    let_master_land_idx = np.unique(np.concatenate([e["flat_indices"] for e in let_base_entities]))

    for entity in let_base_entities:
      if entity["entity_id"] == "brazil":
        let_brazil_modern_idx = entity["flat_indices"]
      if entity["entity_id"] == "united_states_of_america":
        let_usa_modern_idx = entity["flat_indices"]
      if entity["entity_id"] == "france":
        let_france_modern_idx = entity["flat_indices"]

    # 1. Brazil 1650: Portuguese Brazil + Dutch West India Company
    let_b1650_geom = self.b_extract_phersu_geom("1650.01.01.json", ["Portuguese Brazil", "Dutch West India Company"], let_sa_box)
    if let_b1650_geom:
      let_raw_idx = self.rasteriser.A_rasteriseGeometry(let_b1650_geom)
      let_idx = np.intersect1d(let_raw_idx, let_brazil_modern_idx)
      let_historical_entities.append({"entity_id": "brazil_1650", "flat_indices": let_idx})

    # 2. Brazil 1800: Portuguese Brazil in South America
    let_b1800_geom = self.b_extract_phersu_geom("1800.01.01.json", ["Portuguese Brazil"], let_sa_box)
    if let_b1800_geom:
      let_raw_idx = self.rasteriser.A_rasteriseGeometry(let_b1800_geom)
      let_idx = np.intersect1d(let_raw_idx, let_brazil_modern_idx)
      let_historical_entities.append({"entity_id": "brazil_1800", "flat_indices": let_idx})

    # 3. United States 1800: USA in 1800
    let_usa1800_geom = self.b_extract_phersu_geom("1800.01.01.json", ["USA"])
    if let_usa1800_geom:
      let_raw_idx = self.rasteriser.A_rasteriseGeometry(let_usa1800_geom)
      let_idx = np.intersect1d(let_raw_idx, let_usa_modern_idx)
      let_historical_entities.append({"entity_id": "united_states_1800", "flat_indices": let_idx})

    # 4. France 1900: French Third Republic (without Alsace-Lorraine)
    let_fra1900_geom = self.b_extract_phersu_geom("1900.01.01.json", ["French Third Republic"])
    if let_fra1900_geom:
      let_raw_idx = self.rasteriser.A_rasteriseGeometry(let_fra1900_geom)
      let_idx = np.intersect1d(let_raw_idx, let_france_modern_idx)
      let_historical_entities.append({"entity_id": "france_1900", "flat_indices": let_idx})

    # 5. Bolivia 1900: Republic of Bolivia (including Acre)
    let_bol1900_geom = self.b_extract_phersu_geom("1900.01.01.json", ["Republic of Bolivia"])
    if let_bol1900_geom:
      let_raw_idx = self.rasteriser.A_rasteriseGeometry(let_bol1900_geom)
      let_idx = np.intersect1d(let_raw_idx, let_master_land_idx)
      let_historical_entities.append({"entity_id": "bolivia_1900", "flat_indices": let_idx})

    # 6. British India 1900: British India + Princely States
    let_p1900 = os.path.join(self.phersu_dir, "1900.01.01.json")
    if os.path.exists(let_p1900):
      with open(let_p1900, "r", encoding="utf-8") as let_fs:
        let_d1900 = json.load(let_fs)
      for feature in let_d1900.get("features", []):
        let_s = feature.get("properties", {}).get("state", "").replace("\n", " ")
        if "British India" in let_s or "(Princely State)" in let_s:
          let_g = shape(feature["geometry"])
          if let_g.intersects(let_india_box):
            let_raj_parts.append(let_g.intersection(let_india_box))
      if let_raj_parts:
        let_raw_idx = self.rasteriser.A_rasteriseGeometry(unary_union(let_raj_parts))
        let_idx = np.intersect1d(let_raw_idx, let_master_land_idx)
        let_historical_entities.append({"entity_id": "india_1900", "flat_indices": let_idx})

    # 7. Greece 1920: Kingdom of Greece + Eastern Thrace/Smyrna occupation
    let_gre1920_geom = self.b_extract_phersu_geom("1920.01.01.json", ["Kingdom of Greece", "Greece (Military Occupation)"])
    if let_gre1920_geom:
      let_raw_idx = self.rasteriser.A_rasteriseGeometry(let_gre1920_geom)
      let_idx = np.intersect1d(let_raw_idx, let_master_land_idx)
      let_historical_entities.append({"entity_id": "greece_1920", "flat_indices": let_idx})

    # 8. Russia 1500: Grand Duchy of Moscow
    let_rus1500_geom = self.b_extract_phersu_geom("1500.01.01.json", ["Grand Duchy of Moscow"])
    if let_rus1500_geom:
      let_raw_idx = self.rasteriser.A_rasteriseGeometry(let_rus1500_geom)
      let_idx = np.intersect1d(let_raw_idx, let_master_land_idx)
      let_historical_entities.append({"entity_id": "russia_1500", "flat_indices": let_idx})

    # 9. Russia 1650: Tsardom of Russia
    let_rus1650_geom = self.b_extract_phersu_geom("1650.01.01.json", ["Tsardom of Russia"])
    if let_rus1650_geom:
      let_raw_idx = self.rasteriser.A_rasteriseGeometry(let_rus1650_geom)
      let_idx = np.intersect1d(let_raw_idx, let_master_land_idx)
      let_historical_entities.append({"entity_id": "russia_1650", "flat_indices": let_idx})

    # 10. Russian Empire 1800: Russian Empire
    let_rus1800_geom = self.b_extract_phersu_geom("1800.01.01.json", ["Russian Empire"])
    if let_rus1800_geom:
      let_raw_idx = self.rasteriser.A_rasteriseGeometry(let_rus1800_geom)
      let_idx = np.intersect1d(let_raw_idx, let_master_land_idx)
      let_historical_entities.append({"entity_id": "russia_1800", "flat_indices": let_idx})

    # 11. Russian Empire 1900: Russian Empire
    let_rus1900_geom = self.b_extract_phersu_geom("1900.01.01.json", ["Russian Empire"])
    if let_rus1900_geom:
      let_raw_idx = self.rasteriser.A_rasteriseGeometry(let_rus1900_geom)
      let_idx = np.intersect1d(let_raw_idx, let_master_land_idx)
      let_historical_entities.append({"entity_id": "russia_1900", "flat_indices": let_idx})

    # 12. Venice 1500, 1650, 1800: Republic of Venice
    let_v1500_geom = self.b_extract_phersu_geom("1500.01.01.json", ["Republic of Venice"])
    if let_v1500_geom:
      let_raw_idx = self.rasteriser.A_rasteriseGeometry(let_v1500_geom)
      let_idx = np.intersect1d(let_raw_idx, let_master_land_idx)
      let_historical_entities.append({"entity_id": "venice_1500", "flat_indices": let_idx})

    let_v1650_geom = self.b_extract_phersu_geom("1650.01.01.json", ["Republic of Venice"])
    if let_v1650_geom:
      let_raw_idx = self.rasteriser.A_rasteriseGeometry(let_v1650_geom)
      let_idx = np.intersect1d(let_raw_idx, let_master_land_idx)
      let_historical_entities.append({"entity_id": "venice_1650", "flat_indices": let_idx})

    for entity in let_base_entities:
      if entity["entity_id"] == "venice":
        let_historical_entities.append({"entity_id": "venice_1800", "flat_indices": entity["flat_indices"]})

    # Return statement
    return let_historical_entities


  def e_partition_equivalence_classes (self, arg1_entities_array, arg2_png_path, arg3_seed):
    """Partitions overlapping entities into atomic equivalence classes with certified zero collisions.

    @param {list} arg1_entities_array - Array of entity dicts with 'entity_id' and 'flat_indices'.
    @param {str} arg2_png_path - Output file path for provinces.png.
    @param {int} arg3_seed - Deterministic palette seed.
    @return {dict} Metrics and mapping of entity_id -> list of [R, G, B] colour codes.
    """
    # Convert from parameters
    let_entities_array = arg1_entities_array if isinstance(arg1_entities_array, list) else []
    let_png_path = str(arg2_png_path or "")
    let_seed = int(arg3_seed)

    # Declare local instance variables
    let_active_px = None
    let_deg = np.zeros(self.rasteriser.total_pixels, dtype=np.uint16)
    let_entity_rgb_out = {}
    let_flat_rgb = np.zeros((self.rasteriser.total_pixels, 3), dtype=np.uint8)
    let_h1 = np.zeros(self.rasteriser.total_pixels, dtype=np.uint64)
    let_h2 = np.zeros(self.rasteriser.total_pixels, dtype=np.uint64)
    let_num_ents = len(let_entities_array)
    let_palette = []
    let_pixel_to_zone = np.zeros(self.rasteriser.total_pixels, dtype=np.int32)
    let_rng = np.random.default_rng(let_seed)
    let_z1 = let_rng.integers(1, (1 << 63) - 1, size=max(1, let_num_ents), dtype=np.uint64)
    let_z2 = let_rng.integers(1, (1 << 63) - 1, size=max(1, let_num_ents), dtype=np.uint64)

    # Function body
    for i in range(let_num_ents):
      let_idx = let_entities_array[i]["flat_indices"]
      if let_idx.size > 0:
        let_h1[let_idx] ^= let_z1[i]
        let_h2[let_idx] ^= let_z2[i]
        let_deg[let_idx] += 1

    let_active_px = np.flatnonzero(let_deg > 0)
    if let_active_px.size == 0:
      self.rasteriser.B_exportRgbPng(let_flat_rgb.reshape(self.rasteriser.height, self.rasteriser.width, 3), let_png_path)
      # Return statement
      return {"covered_pixels": 0, "entity_rgb_masks": let_entity_rgb_out, "province_count": 0}

    let_sig_dtype = np.dtype([("h1", "<u8"), ("h2", "<u8"), ("deg", "<u2")])
    let_sigs = np.empty(let_active_px.size, dtype=let_sig_dtype)
    let_sigs["h1"] = let_h1[let_active_px]
    let_sigs["h2"] = let_h2[let_active_px]
    let_sigs["deg"] = let_deg[let_active_px]

    let_unique_sigs, let_inv_idx = np.unique(let_sigs, return_inverse=True)
    let_num_zones = int(let_unique_sigs.size)
    let_pixel_to_zone[let_active_px] = let_inv_idx.astype(np.int32) + 1

    let_order = np.argsort(let_inv_idx, kind="mergesort")
    let_sorted_active_px = let_active_px[let_order]
    let_sorted_inv = let_inv_idx[let_order]
    let_zone_splits = np.flatnonzero(np.diff(let_sorted_inv)) + 1
    let_zone_pixel_arrays = np.split(let_sorted_active_px, let_zone_splits)

    let_palette = self.generate_palette(let_num_zones, let_seed)

    for i in range(let_num_ents):
      let_eid = let_entities_array[i]["entity_id"]
      let_idx = let_entities_array[i]["flat_indices"]
      if let_idx.size == 0:
        let_entity_rgb_out[let_eid] = []
        continue
      let_z_hits = np.unique(let_pixel_to_zone[let_idx])
      let_rgb_tuples = []
      for x in range(let_z_hits.size):
        let_zi = int(let_z_hits[x]) - 1
        if let_zi >= 0:
          let_rgb_c = let_palette[let_zi]
          let_rgb_tuples.append((int(let_rgb_c[0]), int(let_rgb_c[1]), int(let_rgb_c[2])))
      let_rgb_tuples.sort()
      let_entity_rgb_out[let_eid] = [[t[0], t[1], t[2]] for t in let_rgb_tuples]

    for i in range(let_num_zones):
      let_z_px = let_zone_pixel_arrays[i]
      let_rgb_c = let_palette[i]
      let_flat_rgb[let_z_px, 0] = let_rgb_c[0]
      let_flat_rgb[let_z_px, 1] = let_rgb_c[1]
      let_flat_rgb[let_z_px, 2] = let_rgb_c[2]

    self.rasteriser.B_exportRgbPng(let_flat_rgb.reshape(self.rasteriser.height, self.rasteriser.width, 3), let_png_path)

    # Return statement
    return {
      "covered_pixels": int(let_active_px.size),
      "entity_rgb_masks": let_entity_rgb_out,
      "province_count": let_num_zones
    }


  def f_build_country_masks (self, arg1_entity_rgb_masks):
    """Compiles the comprehensive country_masks.json dictionary with historical and regional aliases.

    @param {dict} arg1_entity_rgb_masks - Equivalence class RGB mask mapping.
    @return {dict} Flat dictionary mapping country identifier to list of [R, G, B] triplets.
    """
    # Convert from parameters
    let_entity_rgb_masks = arg1_entity_rgb_masks if isinstance(arg1_entity_rgb_masks, dict) else {}

    # Declare local instance variables
    let_country_masks = {}

    # Function body
    # 1. Base atomic and historical entities
    for key, colours in sorted(let_entity_rgb_masks.items()):
      let_country_masks[key] = colours

    # 2. United Kingdom aliases and constituents
    let_eng_col = let_entity_rgb_masks.get("england", [])
    let_nir_col = let_entity_rgb_masks.get("northern_ireland", [])
    let_sct_col = let_entity_rgb_masks.get("scotland", [])
    let_wls_col = let_entity_rgb_masks.get("wales", [])
    let_uk_cols = sorted(set(tuple(c) for c in (let_eng_col + let_sct_col + let_wls_col + let_nir_col)))
    let_gb_cols = sorted(set(tuple(c) for c in (let_eng_col + let_sct_col + let_wls_col)))

    let_country_masks["united_kingdom"] = [[t[0], t[1], t[2]] for t in let_uk_cols]
    let_country_masks["uk"] = let_country_masks["united_kingdom"]
    let_country_masks["great_britain"] = [[t[0], t[1], t[2]] for t in let_gb_cols]

    # 3. Italy and Venice aliases
    let_ita_rest = let_entity_rgb_masks.get("italy_rest", [])
    let_venice = let_entity_rgb_masks.get("venice", [])
    let_italy_cols = sorted(set(tuple(c) for c in (let_ita_rest + let_venice)))

    let_country_masks["italy"] = [[t[0], t[1], t[2]] for t in let_italy_cols]
    let_country_masks["republic_of_venice"] = let_venice

    # 4. India and Goa aliases
    let_goa = let_entity_rgb_masks.get("goa", [])
    let_ind_rest = let_entity_rgb_masks.get("india_rest", [])
    let_india_cols = sorted(set(tuple(c) for c in (let_ind_rest + let_goa)))

    let_country_masks["india"] = [[t[0], t[1], t[2]] for t in let_india_cols]
    let_country_masks["company_raj"] = let_country_masks["india"]
    let_country_masks["deccan"] = let_country_masks["india"]
    let_country_masks["bihar"] = let_country_masks["india"]
    let_country_masks["portuguese_goa"] = let_goa

    # 5. Indonesia, Java, and Outer Islands
    let_java = let_entity_rgb_masks.get("java", [])
    let_outer_indo = let_entity_rgb_masks.get("indonesia_outer_islands", [])
    let_indo_cols = sorted(set(tuple(c) for c in (let_java + let_outer_indo)))

    let_country_masks["indonesia"] = [[t[0], t[1], t[2]] for t in let_indo_cols]
    let_country_masks["java_and_madura"] = let_java
    let_country_masks["java_1650"] = let_java
    let_country_masks["java_1800"] = let_java
    let_country_masks["java_1900"] = let_java

    # 6. Malaysia, Malaya, and Borneo
    let_brunei = let_entity_rgb_masks.get("brunei", [])
    let_malaya = let_entity_rgb_masks.get("british_malaya", [])
    let_my_borneo = let_entity_rgb_masks.get("british_borneo_malaysia", [])
    let_borneo_cols = sorted(set(tuple(c) for c in (let_my_borneo + let_brunei)))
    let_malaysia_cols = sorted(set(tuple(c) for c in (let_malaya + let_my_borneo)))

    let_country_masks["malaysia"] = [[t[0], t[1], t[2]] for t in let_malaysia_cols]
    let_country_masks["malaya"] = let_malaya
    let_country_masks["british_borneo"] = [[t[0], t[1], t[2]] for t in let_borneo_cols]
    let_country_masks["borneo"] = let_country_masks["british_borneo"]

    # 7. Ceylon / Sri Lanka
    let_ceylon = let_entity_rgb_masks.get("sri_lanka", [])
    let_country_masks["ceylon"] = let_ceylon
    let_country_masks["ceylon_1650"] = let_ceylon

    # 8. United States aliases
    let_usa = let_entity_rgb_masks.get("united_states_of_america", [])
    let_country_masks["united_states"] = let_usa
    let_country_masks["usa"] = let_usa

    # 9. Brazil aliases
    let_brazil = let_entity_rgb_masks.get("brazil", [])
    let_country_masks["brazil_2000"] = let_brazil

    # 10. Russia and Russian Empire aliases
    let_russia = let_entity_rgb_masks.get("russia", [])
    let_country_masks["russia_2000"] = let_russia
    let_country_masks["russian_empire"] = let_entity_rgb_masks.get("russia_1900", let_russia)

    # 11. Bolivia aliases
    let_bolivia = let_entity_rgb_masks.get("bolivia", [])
    let_country_masks["bolivia_2000"] = let_bolivia

    # 12. France and Netherlands
    let_france = let_entity_rgb_masks.get("france", [])
    let_country_masks["france_2000"] = let_france
    let_nld = let_entity_rgb_masks.get("netherlands", [])
    let_country_masks["the_netherlands"] = let_nld

    # Return statement
    return let_country_masks


  def g_build_table_masks (self, arg1_country_masks):
    """Compiles the comprehensive table_masks.json map covering all spreadsheet datasets with era awareness.

    @param {dict} arg1_country_masks - Country masks dictionary.
    @return {dict} Dictionary mapping table identifiers to 'country:<country_key>'.
    """
    # Convert from parameters
    let_country_masks = arg1_country_masks if isinstance(arg1_country_masks, dict) else {}

    # Declare local instance variables
    let_country_key = ""
    let_folder_name = ""
    let_json_files = []
    let_raw_dir = os.path.join(self.input_json_dir, "raw_tables")
    let_stem = ""
    let_table_masks = {}

    # Guard clause
    if not os.path.exists(let_raw_dir):
      print(f"Warning: Raw tables directory not found at {let_raw_dir}")
      # Return statement
      return let_table_masks

    # Function body
    let_json_files = sorted(f for f in os.listdir(let_raw_dir) if f.endswith(".json"))

    for json_file in let_json_files:
      let_stem = Path(json_file).stem
      let_folder_name = self.find_source_folder(let_stem)
      let_country_key = self.resolve_table_country(let_stem, let_folder_name)

      # Fallback to general country if era key missing
      if let_country_key not in let_country_masks and "_" in let_country_key:
        let_fallback = let_country_key.split("_")[0]
        if let_fallback in let_country_masks:
          let_country_key = let_fallback

      let_target = f"country:{let_country_key}"

      # Map filename and stem
      let_table_masks[let_stem] = let_target
      let_table_masks[json_file] = let_target

      # Map directory-qualified variants
      let_table_masks[f"raw_tables/{json_file}"] = let_target
      let_table_masks[f"sectoral_harmonised/{json_file}"] = let_target

      if let_folder_name:
        let_table_masks[f"{let_folder_name}:{let_stem}"] = let_target
        let_table_masks[f"{let_folder_name}/{json_file}"] = let_target

    # Return statement
    return let_table_masks


  def generate_palette (self, arg1_count, arg2_seed):
    """Generates a deterministic, collision-free, high-visibility non-black RGB palette.

    @param {int} arg1_count - Number of distinct colours required.
    @param {int} arg2_seed - Integer seed controlling coprime stride generation.
    @return {list} List of [R, G, B] integer triplets.
    """
    # Convert from parameters
    let_count = max(0, int(arg1_count))
    let_seed = int(arg2_seed)

    # Declare local instance variables
    let_b_ch = 0
    let_colours_array = []
    let_g_ch = 0
    let_r_ch = 0
    let_state = (let_seed*2654435761) & 0xFFFFFF
    let_step = 1046527
    let_used_codes = set([0])

    # Function body
    for _ in range(let_count*4 + 64):
      if len(let_colours_array) >= let_count:
        break
      let_state = (let_state + let_step) & 0xFFFFFF
      if let_state in let_used_codes:
        continue
      let_r_ch = (let_state >> 16) & 0xFF
      let_g_ch = (let_state >> 8) & 0xFF
      let_b_ch = let_state & 0xFF
      if max(let_r_ch, let_g_ch, let_b_ch) < 32:
        continue
      let_used_codes.add(let_state)
      let_colours_array.append([int(let_r_ch), int(let_g_ch), int(let_b_ch)])

    # Return statement
    return let_colours_array


  def h_build_subadmin_and_city_masks (self, arg1_country_masks):
    """Compiles subadmin_masks.json and city_masks.json deliverables.

    @param {dict} arg1_country_masks - Country masks dictionary.
    @return {tuple} (subadmin_masks_map, city_masks_map) dictionaries.
    """
    # Convert from parameters
    let_country_masks = arg1_country_masks if isinstance(arg1_country_masks, dict) else {}

    # Declare local instance variables
    let_city_masks = {}
    let_subadmin_entities = [
      "england", "scotland", "wales", "northern_ireland",
      "venice", "republic_of_venice", "goa", "portuguese_goa",
      "java", "indonesia_outer_islands", "british_malaya", "british_borneo"
    ]
    let_subadmin_masks = {}

    # Function body
    for sub_key in let_subadmin_entities:
      if sub_key in let_country_masks:
        let_subadmin_masks[sub_key] = let_country_masks[sub_key]

    # Return statement
    return let_subadmin_masks, let_city_masks


  def i_write_compact_flat_json (self, arg1_path, arg2_flat_map):
    """Serialises a flat JSON map atomically with 2-space indented lines.

    @param {str} arg1_path - Target output file path.
    @param {dict} arg2_flat_map - Dictionary to serialise.
    """
    # Convert from parameters
    let_path = str(arg1_path or "")
    let_flat_map = arg2_flat_map if isinstance(arg2_flat_map, dict) else {}

    # Declare local instance variables
    let_comma = ""
    let_key_str = ""
    let_keys_sorted = sorted(let_flat_map.keys())
    let_lines = ["{"]
    let_num_keys = len(let_keys_sorted)
    let_tmp_path = f"{let_path}.part"
    let_val_str = ""

    # Guard clause
    if not let_path:
      return

    # Function body
    for i, key in enumerate(let_keys_sorted):
      let_comma = "," if i + 1 < let_num_keys else ""
      let_key_str = json.dumps(key, ensure_ascii=False)
      let_val_str = json.dumps(let_flat_map[key], ensure_ascii=False).replace(",", ", ")
      let_lines.append(f"  {let_key_str}: {let_val_str}{let_comma}")
    let_lines.append("}\n")

    os.makedirs(os.path.dirname(os.path.abspath(let_path)), exist_ok=True)
    with open(let_tmp_path, "w", encoding="utf-8") as let_file_stream:
      let_file_stream.write("\n".join(let_lines))
    os.replace(let_tmp_path, let_path)


  def j_run_pipeline (self):
    """Executes the complete areal mask generation pipeline end-to-end.

    @return {dict} Summary metrics of generated masks.
    """
    # Declare local instance variables
    let_all_entities = []
    let_base_entities = []
    let_city_masks = {}
    let_city_path = os.path.join(self.output_dir, str(self.outputs_cfg.get("city_masks_json", "city_masks.json")))
    let_country_masks = {}
    let_country_path = os.path.join(self.output_dir, str(self.outputs_cfg.get("country_masks_json", "country_masks.json")))
    let_historical_entities = []
    let_partition_res = {}
    let_png_filename = str(self.outputs_cfg.get("provinces_png", "provinces.png"))
    let_png_path = os.path.join(self.output_dir, let_png_filename)
    let_seed = int(self.config_obj.get("palette_seed", 104729))
    let_start_time = time.time()
    let_subadmin_masks = {}
    let_subadmin_path = os.path.join(self.output_dir, str(self.outputs_cfg.get("subadmin_masks_json", "subadmin_masks.json")))
    let_table_masks = {}
    let_table_path = os.path.join(self.output_dir, str(self.outputs_cfg.get("table_masks_json", "table_masks.json")))

    # Function body
    print("=== Starting Areal Mask Synthesis Pipeline ===")

    # Step 1: Build modern base entities
    print("Step 1/5: Building base modern territory entities from Natural Earth 10m...")
    let_base_entities = self.c_build_base_entities()
    print(f"Constructed {len(let_base_entities)} modern base entities.")

    # Step 2: Build historical entities from Phersu
    print("Step 2/5: Extracting and rasterising historical border layers from Phersu...")
    let_historical_entities = self.d_build_historical_entities(let_base_entities)
    print(f"Constructed {len(let_historical_entities)} historical border entities.")

    let_all_entities = let_base_entities + let_historical_entities
    print(f"Total entities for equivalence class partitioning: {len(let_all_entities)}")

    # Step 3: Equivalence class partitioning & provinces.png synthesis
    print("Step 3/5: Running Zobrist equivalence class partitioning...")
    let_partition_res = self.e_partition_equivalence_classes(let_all_entities, let_png_path, let_seed)
    print(f"Equivalence classes resolved: {let_partition_res['province_count']} atomic provinces.")
    print(f"Covered pixels: {let_partition_res['covered_pixels']:,}")

    # Step 4: Compile country_masks.json
    print("Step 4/5: Compiling country_masks.json...")
    let_country_masks = self.f_build_country_masks(let_partition_res["entity_rgb_masks"])
    self.i_write_compact_flat_json(let_country_path, let_country_masks)

    # Step 5: Compile table_masks, subadmin_masks, city_masks
    print("Step 5/5: Compiling table, subadmin, and city mask deliverables...")
    let_table_masks = self.g_build_table_masks(let_country_masks)
    self.i_write_compact_flat_json(let_table_path, let_table_masks)

    let_subadmin_masks, let_city_masks = self.h_build_subadmin_and_city_masks(let_country_masks)
    self.i_write_compact_flat_json(let_subadmin_path, let_subadmin_masks)
    self.i_write_compact_flat_json(let_city_path, let_city_masks)

    let_elapsed = time.time() - let_start_time
    print(f"=== Pipeline Complete in {let_elapsed:.2f}s ===")
    print(f"  provinces.png: {self.rasteriser.width}x{self.rasteriser.height} WGS84 Equirectangular")
    print(f"  atomic provinces: {let_partition_res['province_count']}")
    print(f"  country_masks.json: {len(let_country_masks)} country entries")
    print(f"  table_masks.json: {len(let_table_masks)} table entries")
    print(f"  subadmin_masks.json: {len(let_subadmin_masks)} subadmin entries")
    print(f"  city_masks.json: {len(let_city_masks)} city entries")

    # Return statement
    return {
      "atomic_provinces": let_partition_res["province_count"],
      "country_masks": len(let_country_masks),
      "elapsed_seconds": round(let_elapsed, 2),
      "subadmin_masks": len(let_subadmin_masks),
      "table_masks": len(let_table_masks)
    }


  def find_source_folder (self, arg1_stem):
    """Finds the data source directory name for a given table stem.

    @param {str} arg1_stem - Spreadsheet file stem without extension.
    @return {str} Source folder name within data/, or empty string if not found.
    """
    # Convert from parameters
    let_stem = str(arg1_stem or "").strip()

    # Function body
    for root, _, files in os.walk(self.data_dir):
      for file_name in files:
        if Path(file_name).stem == let_stem:
          let_rel = os.path.relpath(root, self.data_dir)
          # Return statement
          return let_rel.split(os.sep)[0]

    # Return statement
    return ""


  def resolve_table_country (self, arg1_stem, arg2_folder):
    """Resolves a table stem and source folder into a canonical era-specific country key.

    @param {str} arg1_stem - Spreadsheet file stem.
    @param {str} arg2_folder - Source folder name.
    @return {str} Canonical country identifier matching an entry in country_masks.json.
    """
    # Convert from parameters
    let_folder = str(arg2_folder or "").lower()
    let_stem = str(arg1_stem or "").lower()

    # Function body
    # 1. Brazil (1650 coastal captaincies, 1800 viceroyalty, or modern)
    if "brazil" in let_stem or "brazil" in let_folder:
      if "1650" in let_stem:
        return "brazil_1650"
      if "1800" in let_stem:
        return "brazil_1800"
      if "1650" in let_folder and "1800" not in let_folder:
        return "brazil_1650"
      if "1800" in let_folder and "1650" not in let_folder:
        return "brazil_1800"
      return "brazil"

    # 2. United States (1800 or modern)
    if "unitedstates" in let_stem or "united_states" in let_stem or "united_states" in let_folder:
      if "1800" in let_stem or "1800" in let_folder:
        return "united_states_1800"
      return "united_states"

    # 3. Russia (1500 Moscow, 1650 Muscovy, 1800/1900 Russian Empire, 2000 modern)
    if "russia" in let_stem or "russia" in let_folder:
      if "1500" in let_stem:
        return "russia_1500"
      if "1650" in let_stem:
        return "russia_1650"
      if "1800" in let_stem:
        return "russia_1800"
      if "1900" in let_stem:
        return "russia_1900"
      return "russia"

    # 4. Venice (1500, 1650, 1800, modern)
    if "venice" in let_stem or "venice" in let_folder:
      if "1500" in let_stem:
        return "venice_1500"
      if any(y in let_stem for y in ["1650", "1660", "1672"]):
        return "venice_1650"
      if any(y in let_stem for y in ["1785", "1800"]):
        return "venice_1800"
      return "venice"

    # 5. Bolivia (1900 pre-Petropolis or 2000 modern)
    if "bolivia" in let_stem or "bolivia" in let_folder:
      if "1900" in let_stem:
        return "bolivia_1900"
      return "bolivia"

    # 6. France (1900/1906 without Alsace-Lorraine or modern)
    if "france" in let_stem or "france" in let_folder:
      if "1900" in let_stem or "1906" in let_stem:
        return "france_1900"
      return "france"

    # 7. Greece (1920 Treaty of Sevres or modern)
    if "greece" in let_stem or "greece" in let_folder:
      if "1920" in let_stem:
        return "greece_1920"
      return "greece"

    # 8. India & Subcontinent (1900 British Raj, 1800 Deccan, Goa, modern)
    if "goa" in let_stem or "goa" in let_folder:
      return "goa"
    if any(k in let_stem for k in ["bihar 1900", "deccan 1900", "india 1900", "sykes"]):
      return "india_1900"
    if any(k in let_stem for k in ["bihar", "deccan", "india"]) or "india" in let_folder:
      return "india"

    # 9. Ceylon (1650 or modern)
    if "ceylon" in let_stem or "ceylon" in let_folder:
      if "1650" in let_stem or "1650" in let_folder:
        return "ceylon_1650"
      return "ceylon"

    # 10. Island Southeast Asia & Java
    if "british borneo" in let_stem or "borneo" in let_stem:
      return "british_borneo"
    if "malaya" in let_stem:
      return "british_malaya"
    if "philippines" in let_stem:
      return "philippines"
    if "outer islands" in let_stem:
      return "indonesia_outer_islands"
    if "java" in let_stem or "java" in let_folder:
      if "1650" in let_stem:
        return "java_1650"
      if "1800" in let_stem:
        return "java_1800"
      if "1900" in let_stem:
        return "java_1900"
      return "java"

    # 11. England & United Kingdom
    if "england" in let_stem or "england" in let_folder:
      return "england"
    if any(k in let_stem for k in ["uk1901", "database calculations"]) or "united_kingdom" in let_folder:
      return "united_kingdom"

    # 12. Standard modern countries
    for country in ["argentina", "belarus", "italy", "japan", "netherlands", "south_africa", "spain", "taiwan", "turkey"]:
      if country in let_stem or country in let_folder or country.replace("_", "") in let_stem:
        return country

    # Return statement
    return "unknown"


  def to_snake_key (self, arg1_name):
    """Converts an arbitrary display name or place string to a normalised snake_case key.

    @param {str} arg1_name - Input string.
    @return {str} Normalised snake_case key.
    """
    # Convert from parameters
    let_name = str(arg1_name or "").strip().lower()

    # Function body
    let_name = re.sub(r"[^\w\s-]", "", let_name)
    let_name = re.sub(r"[\s-]+", "_", let_name)

    # Return statement
    return let_name


if __name__ == "__main__":
  let_generator = ArealMaskGenerator()
  let_generator.j_run_pipeline()
