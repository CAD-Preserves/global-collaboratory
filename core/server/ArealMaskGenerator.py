"""Areal Mask Generator Module.

Synthesises 4320x2160 WGS84 Equirectangular areal masks for top-level countries and historical regions.
Produces provinces.png, country_masks.json, table_masks.json, subadmin_masks.json, and city_masks.json.
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
from shapely.geometry import shape
from shapely.ops import unary_union

from core.server.EquirectangularRasteriser import EquirectangularRasteriser


class ArealMaskGenerator:
  """Orchestrator for synthesising WGS84 Equirectangular areal masks."""

  def __init__(self, arg1_root_dir=None, arg2_options=None):
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
    self.rasteriser = EquirectangularRasteriser(self.config_obj.get("grid", {}))

    os.makedirs(self.cache_dir, exist_ok=True)
    os.makedirs(self.output_dir, exist_ok=True)


  def a_fetch_or_load_layer(self, arg1_layer_name):
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


  def b_build_atomic_geometries(self):
    """Constructs atomic, non-overlapping territory geometries for top-level countries and historical regions.

    Partitions the UK into constituent countries (England, Scotland, Wales, Northern Ireland),
    Italy into Venice/Veneto and Rest of Italy, India into Goa and Rest of India,
    Indonesia into Java and Outer Islands, and Malaysia into British Malaya and British Borneo.

    @return {dict} Dictionary mapping atomic region identifier to Shapely geometry.
    """
    # Declare local instance variables
    let_admin0_by_a3 = {}
    let_admin0_fc = self.a_fetch_or_load_layer("ne_admin0")
    let_admin1_fc = self.a_fetch_or_load_layer("ne_admin1")
    let_atomic_geoms = {}
    let_borneo_my_geom = None
    let_borneo_my_names = {"Labuan", "Sabah", "Sarawak"}
    let_borneo_my_parts = []
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
      let_atomic_geoms[let_key] = shape(feature["geometry"])

    # 2. Partition United Kingdom into England, Scotland, Wales, and Northern Ireland
    let_atomic_geoms["england"] = shape(let_units_by_gu["ENG"]["geometry"])
    let_atomic_geoms["scotland"] = shape(let_units_by_gu["SCT"]["geometry"])
    let_atomic_geoms["wales"] = shape(let_units_by_gu["WLS"]["geometry"])
    let_atomic_geoms["northern_ireland"] = shape(let_units_by_gu["NIR"]["geometry"])

    # 3. Partition Italy into Venice (Veneto) and Rest of Italy
    let_italy_full = shape(let_admin0_by_a3["ITA"]["geometry"])
    for feature in let_admin1_fc.get("features", []):
      if feature.get("properties", {}).get("adm0_a3") == "ITA":
        if feature.get("properties", {}).get("name") in let_veneto_names:
          let_veneto_parts.append(shape(feature["geometry"]))
    let_veneto_geom = unary_union(let_veneto_parts)
    let_italy_rest_geom = let_italy_full.difference(let_veneto_geom)
    let_atomic_geoms["venice"] = let_veneto_geom
    let_atomic_geoms["italy_rest"] = let_italy_rest_geom

    # 4. Partition India into Goa and Rest of India
    let_india_full = shape(let_admin0_by_a3["IND"]["geometry"])
    for feature in let_admin1_fc.get("features", []):
      if feature.get("properties", {}).get("adm0_a3") == "IND":
        if feature.get("properties", {}).get("name") == "Goa":
          let_goa_parts.append(shape(feature["geometry"]))
    let_goa_geom = unary_union(let_goa_parts)
    let_india_rest_geom = let_india_full.difference(let_goa_geom)
    let_atomic_geoms["goa"] = let_goa_geom
    let_atomic_geoms["india_rest"] = let_india_rest_geom

    # 5. Partition Indonesia into Java and Outer Islands
    let_indonesia_full = shape(let_admin0_by_a3["IDN"]["geometry"])
    for feature in let_admin1_fc.get("features", []):
      if feature.get("properties", {}).get("adm0_a3") == "IDN":
        if feature.get("properties", {}).get("name") in let_java_names:
          let_java_parts.append(shape(feature["geometry"]))
    let_java_geom = unary_union(let_java_parts)
    let_outer_indo_geom = let_indonesia_full.difference(let_java_geom)
    let_atomic_geoms["java"] = let_java_geom
    let_atomic_geoms["indonesia_outer_islands"] = let_outer_indo_geom

    # 6. Partition Malaysia into British Malaya (Peninsular) and Malaysian Borneo (Sabah, Sarawak, Labuan)
    let_malaysia_full = shape(let_admin0_by_a3["MYS"]["geometry"])
    for feature in let_admin1_fc.get("features", []):
      if feature.get("properties", {}).get("adm0_a3") == "MYS":
        if feature.get("properties", {}).get("name") in let_borneo_my_names:
          let_borneo_my_parts.append(shape(feature["geometry"]))
    let_borneo_my_geom = unary_union(let_borneo_my_parts)
    let_malaya_geom = let_malaysia_full.difference(let_borneo_my_geom)
    let_atomic_geoms["british_malaya"] = let_malaya_geom
    let_atomic_geoms["british_borneo_malaysia"] = let_borneo_my_geom

    # Return statement
    return let_atomic_geoms


  def c_rasterise_atomic_regions(self, arg1_atomic_geoms):
    """Scanline-rasterises all atomic geometries onto the 4320x2160 Equirectangular grid.

    Assigns every pixel to a unique atomic territory ID on a single collision-free grid.
    Sorts assignment by area descending and preserves at least 1 pixel for micro-territories.

    @param {dict} arg1_atomic_geoms - Dictionary mapping region identifier to Shapely geometry.
    @return {dict} Dictionary mapping region identifier to 1D numpy array of unique pixel indices.
    """
    # Convert from parameters
    let_atomic_geoms = arg1_atomic_geoms

    # Declare local instance variables
    let_atomic_masks = {}
    let_exact_indices = None
    let_flat_grid = np.zeros(self.rasteriser.total_pixels, dtype=np.uint16)
    let_raw_masks = {}
    let_region_keys = sorted(let_atomic_geoms.keys())

    # Function body
    for region_idx, region_key in enumerate(let_region_keys):
      let_geom = let_atomic_geoms[region_key]
      let_raw_masks[region_key] = self.rasteriser.A_rasteriseGeometry(let_geom)

    # 1. First pass: Assign largest regions first so small territories retain boundary pixels
    let_sorted_regions = sorted(let_region_keys, key=lambda k: len(let_raw_masks[k]), reverse=True)
    for region_key in let_sorted_regions:
      let_region_idx = let_region_keys.index(region_key)
      let_indices = let_raw_masks[region_key]
      if let_indices.size > 0:
        let_flat_grid[let_indices] = let_region_idx + 1

    # 2. Second pass: Guarantee at least 1 pixel for every region with valid geometry
    for region_idx, region_key in enumerate(let_region_keys):
      let_exact = np.flatnonzero(let_flat_grid == region_idx + 1)
      if let_exact.size == 0 and let_raw_masks[region_key].size > 0:
        let_rep_pixel = int(let_raw_masks[region_key][0])
        # Find adjacent pixel if rep pixel is already owned by a single-pixel territory
        let_owner = let_flat_grid[let_rep_pixel]
        if let_owner > 0 and np.count_nonzero(let_flat_grid == let_owner) <= 1:
          let_rep_pixel = self.find_available_neighbor(let_flat_grid, let_rep_pixel)
        let_flat_grid[let_rep_pixel] = region_idx + 1

    # 3. Third pass: Extract final exact collision-free pixel indices
    for region_idx, region_key in enumerate(let_region_keys):
      let_exact_indices = np.flatnonzero(let_flat_grid == region_idx + 1).astype(np.int32)
      let_atomic_masks[region_key] = let_exact_indices

    # Return statement
    return let_atomic_masks


  def d_generate_palette(self, arg1_count, arg2_seed):
    """Generates a deterministic, collision-free, high-visibility non-black RGB palette.

    @param {int} arg1_count - Number of distinct colours required.
    @param {int} arg2_seed - Integer seed controlling the coprime stride generator.
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


  def e_synthesise_provinces_png(self, arg1_atomic_masks):
    """Paints atomic regions onto a 4320x2160 uint8 RGB raster and exports provinces.png.

    @param {dict} arg1_atomic_masks - Dictionary mapping region key to pixel indices.
    @return {dict} Dictionary mapping region key to its assigned [R, G, B] triplet.
    """
    # Convert from parameters
    let_atomic_masks = arg1_atomic_masks

    # Declare local instance variables
    let_atomic_colours = {}
    let_colour = []
    let_indices = None
    let_palette = []
    let_palette_seed = int(self.config_obj.get("palette_seed", 104729))
    let_png_filename = str(self.outputs_cfg.get("provinces_png", "provinces.png"))
    let_png_path = os.path.join(self.output_dir, let_png_filename)
    let_region_keys = sorted(let_atomic_masks.keys())
    let_rgb_buffer = np.zeros((self.rasteriser.height, self.rasteriser.width, 3), dtype=np.uint8)
    let_rgb_flat = let_rgb_buffer.reshape(-1, 3)

    # Function body
    let_palette = self.d_generate_palette(len(let_region_keys), let_palette_seed)

    for idx, region_key in enumerate(let_region_keys):
      let_colour = let_palette[idx]
      let_indices = let_atomic_masks[region_key]
      let_atomic_colours[region_key] = let_colour
      if let_indices.size > 0:
        let_rgb_flat[let_indices] = let_colour

    self.rasteriser.B_exportRgbPng(let_rgb_buffer, let_png_path)
    print(f"Synthesised provinces.png ({self.rasteriser.width}x{self.rasteriser.height}) at {let_png_path}")

    # Return statement
    return let_atomic_colours


  def f_build_country_masks(self, arg1_atomic_colours):
    """Builds the comprehensive country_masks.json map.

    Maps sovereign countries, overseas territories, and historical entities to their RGB masks.
    Constituent sub-entities (such as UK, Italy, India, Indonesia, Malaysia) are mapped
    to the union of their atomic colourcodes.

    @param {dict} arg1_atomic_colours - Dictionary mapping atomic region key to [R, G, B].
    @return {dict} Flat dictionary mapping country identifier to list of [R, G, B] triplets.
    """
    # Convert from parameters
    let_atomic_colours = arg1_atomic_colours

    # Declare local instance variables
    let_country_masks = {}

    # Function body
    # 1. Base atomic regions (each gets a single flat RGB colour)
    for region_key, colour in sorted(let_atomic_colours.items()):
      let_country_masks[region_key] = [colour]

    # 2. Historical & Regional Composite Aliases
    # United Kingdom and constituents
    let_eng_col = let_atomic_colours.get("england")
    let_nir_col = let_atomic_colours.get("northern_ireland")
    let_sct_col = let_atomic_colours.get("scotland")
    let_wls_col = let_atomic_colours.get("wales")
    let_uk_cols = [c for c in [let_eng_col, let_sct_col, let_wls_col, let_nir_col] if c is not None]

    let_country_masks["united_kingdom"] = sorted(let_uk_cols)
    let_country_masks["uk"] = sorted(let_uk_cols)
    let_country_masks["great_britain"] = sorted([c for c in [let_eng_col, let_sct_col, let_wls_col] if c is not None])

    # Italy and Venice
    let_ita_rest_col = let_atomic_colours.get("italy_rest")
    let_venice_col = let_atomic_colours.get("venice")
    let_italy_cols = [c for c in [let_ita_rest_col, let_venice_col] if c is not None]

    let_country_masks["italy"] = sorted(let_italy_cols)
    let_country_masks["republic_of_venice"] = [let_venice_col] if let_venice_col else []

    # India and Goa
    let_goa_col = let_atomic_colours.get("goa")
    let_ind_rest_col = let_atomic_colours.get("india_rest")
    let_india_cols = [c for c in [let_ind_rest_col, let_goa_col] if c is not None]

    let_country_masks["india"] = sorted(let_india_cols)
    let_country_masks["company_raj"] = sorted(let_india_cols)
    let_country_masks["deccan"] = sorted(let_india_cols)
    let_country_masks["bihar"] = sorted(let_india_cols)
    let_country_masks["portuguese_goa"] = [let_goa_col] if let_goa_col else []

    # Indonesia, Java, and Outer Islands
    let_java_col = let_atomic_colours.get("java")
    let_outer_indo_col = let_atomic_colours.get("indonesia_outer_islands")
    let_indonesia_cols = [c for c in [let_java_col, let_outer_indo_col] if c is not None]

    let_country_masks["indonesia"] = sorted(let_indonesia_cols)
    let_country_masks["java_and_madura"] = [let_java_col] if let_java_col else []

    # Malaysia, British Malaya, and British Borneo
    let_brunei_col = let_atomic_colours.get("brunei")
    let_malaya_col = let_atomic_colours.get("british_malaya")
    let_my_borneo_col = let_atomic_colours.get("british_borneo_malaysia")
    let_borneo_cols = [c for c in [let_my_borneo_col, let_brunei_col] if c is not None]
    let_malaysia_cols = [c for c in [let_malaya_col, let_my_borneo_col] if c is not None]

    let_country_masks["malaysia"] = sorted(let_malaysia_cols)
    let_country_masks["malaya"] = [let_malaya_col] if let_malaya_col else []
    let_country_masks["british_borneo"] = sorted(let_borneo_cols)
    let_country_masks["borneo"] = sorted(let_borneo_cols)

    # Ceylon / Sri Lanka
    let_lka_col = let_atomic_colours.get("sri_lanka")
    if let_lka_col:
      let_country_masks["ceylon"] = [let_lka_col]

    # United States
    let_usa_col = let_atomic_colours.get("united_states_of_america")
    if let_usa_col:
      let_country_masks["united_states"] = [let_usa_col]
      let_country_masks["usa"] = [let_usa_col]

    # Netherlands
    let_nld_col = let_atomic_colours.get("netherlands")
    if let_nld_col:
      let_country_masks["the_netherlands"] = [let_nld_col]

    # Russia and Russian Empire
    let_belarus_col = let_atomic_colours.get("belarus")
    let_russia_col = let_atomic_colours.get("russia")
    let_russian_empire_cols = [c for c in [let_russia_col, let_belarus_col] if c is not None]

    let_country_masks["russian_empire"] = sorted(let_russian_empire_cols)

    # Return statement
    return let_country_masks


  def g_build_table_masks(self):
    """Builds the comprehensive table_masks.json map covering all spreadsheet datasets.

    Maps table filenames, stems, folder prefixes, and path representations
    to their target country masks.

    @return {dict} Dictionary mapping table identifiers to 'country:<country_key>'.
    """
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


  def h_build_subadmin_and_city_masks(self, arg1_atomic_colours):
    """Builds subadmin_masks.json and city_masks.json deliverables.

    @param {dict} arg1_atomic_colours - Dictionary mapping atomic region key to [R, G, B].
    @return {tuple} (subadmin_masks_map, city_masks_map) dictionaries.
    """
    # Convert from parameters
    let_atomic_colours = arg1_atomic_colours

    # Declare local instance variables
    let_city_masks = {}
    let_subadmin_masks = {}

    # Function body
    let_subadmin_entities = [
      ("england", ["england"]),
      ("scotland", ["scotland"]),
      ("wales", ["wales"]),
      ("northern_ireland", ["northern_ireland"]),
      ("venice", ["venice"]),
      ("republic_of_venice", ["venice"]),
      ("goa", ["goa"]),
      ("portuguese_goa", ["goa"]),
      ("java", ["java"]),
      ("indonesia_outer_islands", ["indonesia_outer_islands"]),
      ("british_malaya", ["british_malaya"]),
      ("british_borneo", ["british_borneo_malaysia", "brunei"]),
    ]

    for sub_key, atomic_keys in let_subadmin_entities:
      let_cols = [let_atomic_colours[k] for k in atomic_keys if k in let_atomic_colours]
      if let_cols:
        let_subadmin_masks[sub_key] = sorted(let_cols)

    # Return statement
    return let_subadmin_masks, let_city_masks


  def i_write_compact_flat_json(self, arg1_path, arg2_flat_map):
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


  def j_run_pipeline(self):
    """Executes the complete areal mask generation pipeline end-to-end.

    @return {dict} Summary metrics of generated masks.
    """
    # Declare local instance variables
    let_atomic_colours = {}
    let_atomic_geoms = {}
    let_atomic_masks = {}
    let_city_masks = {}
    let_city_path = os.path.join(self.output_dir, str(self.outputs_cfg.get("city_masks_json", "city_masks.json")))
    let_country_masks = {}
    let_country_path = os.path.join(self.output_dir, str(self.outputs_cfg.get("country_masks_json", "country_masks.json")))
    let_start_time = time.time()
    let_subadmin_masks = {}
    let_subadmin_path = os.path.join(self.output_dir, str(self.outputs_cfg.get("subadmin_masks_json", "subadmin_masks.json")))
    let_table_masks = {}
    let_table_path = os.path.join(self.output_dir, str(self.outputs_cfg.get("table_masks_json", "table_masks.json")))

    # Function body
    print("=== Starting Areal Mask Synthesis Pipeline ===")

    # Step A-B: Build atomic geometries
    print("Step 1/5: Building atomic territory geometries...")
    let_atomic_geoms = self.b_build_atomic_geometries()
    print(f"Constructed {len(let_atomic_geoms)} atomic territory geometries.")

    # Step C: Rasterise atomic geometries onto 4320x2160 Equirectangular grid
    print("Step 2/5: Scanline-rasterising atomic geometries onto 4320x2160 grid...")
    let_atomic_masks = self.c_rasterise_atomic_regions(let_atomic_geoms)

    # Step D: Synthesise provinces.png
    print("Step 3/5: Synthesising collision-free provinces.png raster...")
    let_atomic_colours = self.e_synthesise_provinces_png(let_atomic_masks)

    # Step E: Build country_masks.json
    print("Step 4/5: Compiling country_masks.json...")
    let_country_masks = self.f_build_country_masks(let_atomic_colours)
    self.i_write_compact_flat_json(let_country_path, let_country_masks)

    # Step F-G: Build table_masks.json, subadmin_masks.json, and city_masks.json
    print("Step 5/5: Compiling table, subadmin, and city mask deliverables...")
    let_table_masks = self.g_build_table_masks()
    self.i_write_compact_flat_json(let_table_path, let_table_masks)

    let_subadmin_masks, let_city_masks = self.h_build_subadmin_and_city_masks(let_atomic_colours)
    self.i_write_compact_flat_json(let_subadmin_path, let_subadmin_masks)
    self.i_write_compact_flat_json(let_city_path, let_city_masks)

    let_elapsed = time.time() - let_start_time
    print(f"=== Pipeline Complete in {let_elapsed:.2f}s ===")
    print(f"  provinces.png: {self.rasteriser.width}x{self.rasteriser.height} WGS84 Equirectangular")
    print(f"  country_masks.json: {len(let_country_masks)} country entries")
    print(f"  table_masks.json: {len(let_table_masks)} table entries")
    print(f"  subadmin_masks.json: {len(let_subadmin_masks)} subadmin entries")
    print(f"  city_masks.json: {len(let_city_masks)} city entries")

    # Return statement
    return {
      "atomic_regions": len(let_atomic_geoms),
      "country_masks": len(let_country_masks),
      "elapsed_seconds": round(let_elapsed, 2),
      "subadmin_masks": len(let_subadmin_masks),
      "table_masks": len(let_table_masks)
    }


  def find_available_neighbor(self, arg1_flat_grid, arg2_pixel_index):
    """Finds an available adjacent pixel (either ocean or from a large country) for a micro-territory.

    @param {np.ndarray} arg1_flat_grid - 1D raster array of allocated region indices.
    @param {int} arg2_pixel_index - Flat pixel index (y*width + x).
    @return {int} New flat pixel index.
    """
    # Convert from parameters
    let_flat_grid = arg1_flat_grid
    let_p = int(arg2_pixel_index)

    # Declare local instance variables
    let_h = self.rasteriser.height
    let_w = self.rasteriser.width
    let_x = let_p % let_w
    let_y = let_p // let_w

    # Function body
    for dy in [0, -1, 1]:
      for dx in [1, -1, 2, -2]:
        let_nx = (let_x + dx) % let_w
        let_ny = min(let_h - 1, max(0, let_y + dy))
        let_np_idx = let_ny*let_w + let_nx
        let_val = let_flat_grid[let_np_idx]
        if let_val == 0 or np.count_nonzero(let_flat_grid == let_val) > 10:
          # Return statement
          return let_np_idx

    # Return statement
    return let_p


  def find_source_folder(self, arg1_stem):
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


  def resolve_table_country(self, arg1_stem, arg2_folder):
    """Resolves a table stem and source folder into a canonical country key.

    @param {str} arg1_stem - Spreadsheet file stem.
    @param {str} arg2_folder - Source folder name.
    @return {str} Canonical country identifier matching an entry in country_masks.json.
    """
    # Convert from parameters
    let_folder = str(arg2_folder or "").lower()
    let_stem = str(arg1_stem or "").lower()

    # Function body
    if "argentina" in let_folder or "argentina" in let_stem:
      return "argentina"
    if "belarus" in let_folder or "belarus" in let_stem:
      return "belarus"
    if "bolivia" in let_folder or "bolivia" in let_stem:
      return "bolivia"
    if "brazil" in let_folder or "brazil" in let_stem:
      return "brazil"
    if "ceylon" in let_folder or "ceylon" in let_stem:
      return "ceylon"
    if "england" in let_folder or "england" in let_stem:
      return "england"
    if "france" in let_folder or "france" in let_stem:
      return "france"
    if "goa" in let_folder or "goa" in let_stem:
      return "goa"
    if "greece" in let_folder or "greece" in let_stem:
      return "greece"
    if "bihar" in let_stem or "deccan" in let_stem or "india" in let_stem or "india" in let_folder:
      return "india"
    if "british borneo" in let_stem or "borneo" in let_stem:
      return "british_borneo"
    if "malaya" in let_stem:
      return "british_malaya"
    if "philippines" in let_stem:
      return "philippines"
    if "outer islands" in let_stem:
      return "indonesia_outer_islands"
    if "java" in let_stem or "java" in let_folder:
      return "java"
    if "italy" in let_folder or "italy" in let_stem:
      return "italy"
    if "japan" in let_folder or "japan" in let_stem:
      return "japan"
    if "netherlands" in let_folder or "netherlands" in let_stem:
      return "netherlands"
    if "russia" in let_folder or "russia" in let_stem:
      return "russia"
    if "southafrica" in let_stem or "south_africa" in let_folder or "south_africa" in let_stem:
      return "south_africa"
    if "spain" in let_folder or "spain" in let_stem:
      return "spain"
    if "taiwan" in let_folder or "taiwan" in let_stem:
      return "taiwan"
    if "turkey" in let_folder or "turkey" in let_stem:
      return "turkey"
    if "uk1901" in let_stem or "united_kingdom" in let_folder:
      return "united_kingdom"
    if "unitedstates" in let_stem or "united_states" in let_folder or "united_states" in let_stem:
      return "united_states"
    if "venice" in let_folder or "venice" in let_stem:
      return "venice"

    # Return statement
    return "unknown"


  def to_snake_key(self, arg1_name):
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
