"""@brief Synthesises the collision-free 4320x2160 RGB provinces.png raster and exports the 4 flat JSON mask maps."""

import os
import sys
import numpy as np
import orjson


class ProvinceMapSynthesizer:
  """@brief Partitions overlapping historical and modern masks into atomic RGB provinces and exports flat JSON deliverables."""

  def __init__ (self, arg1_root_dir, arg2_config_obj, arg3_rasteriser):
    """
    @brief Initialise ProvinceMapSynthesizer with workspace root, config dictionary and EquirectangularRasteriser.
    @param arg1_root_dir Repository root path.
    @param arg2_config_obj Parsed areal_mask_config.json5 dictionary.
    @param arg3_rasteriser EquirectangularRasteriser instance.
    """
    #Convert from parameters
    root_dir = str(arg1_root_dir or "")
    config_obj = arg2_config_obj if isinstance(arg2_config_obj, dict) else {}
    rasteriser = arg3_rasteriser

    #Declare local instance variables
    out_rel = config_obj.get("paths", {}).get("output_dir", os.path.join("output", "areal_masks"))
    self.config_obj = config_obj
    self.entity_rgb_lookup = {}
    self.output_dir = os.path.join(root_dir, out_rel)
    self.outputs_cfg = config_obj.get("outputs", {})
    self.palette_seed = int(config_obj.get("palette_seed", 104729))
    self.province_count = 0
    self.rasteriser = rasteriser
    self.root_dir = root_dir

    os.makedirs(self.output_dir, exist_ok=True)


  def A_synthesiseProvincesPng (self, arg1_countries_map, arg2_divisions_map):
    """
    @brief Step A: Partition all modern/historical country and admin-division masks into atomic RGB provinces on provinces.png.
    @param arg1_countries_map Dictionary of resolved canonical country entities.
    @param arg2_divisions_map Dictionary of resolved canonical admin-division entities.
    @return Dictionary containing province_count, covered_pixels and png_path.
    """
    #Convert from parameters
    countries_map = arg1_countries_map if isinstance(arg1_countries_map, dict) else {}
    divisions_map = arg2_divisions_map if isinstance(arg2_divisions_map, dict) else {}

    #Declare local instance variables
    combined_entities = []
    country_ids = sorted(countries_map.keys())
    div_ids = sorted(divisions_map.keys())
    png_filename = str(self.outputs_cfg.get("provinces_png", "provinces.png"))
    png_path = os.path.join(self.output_dir, png_filename)
    synth_res = {}

    for i in range(len(country_ids)):
      combined_entities.append(countries_map[country_ids[i]])
    for i in range(len(div_ids)):
      if divisions_map[div_ids[i]].get("canonical_key"):
        combined_entities.append(divisions_map[div_ids[i]])

    synth_res = self.partitionEquivalenceClasses(combined_entities, png_path, self.palette_seed)
    self.province_count = synth_res["province_count"]
    self.entity_rgb_lookup = synth_res["entity_rgb_masks"]

    #Return statement
    return {
      "covered_pixels": synth_res["covered_pixels"],
      "png_path": png_path,
      "province_count": self.province_count
    }


  def B_registerAdminGroupMasks (self, arg1_divisions_map):
    """
    @brief Step B: Aggregate constituent province [R, G, B] colourcodes per canonical parent subadministrative group.
    @param arg1_divisions_map Dictionary mapping division entity_id -> resolved division dictionary.
    @return Updated entity_rgb_lookup dictionary.
    """
    #Convert from parameters
    divisions_map = arg1_divisions_map if isinstance(arg1_divisions_map, dict) else {}

    #Declare local instance variables
    div_ids = sorted(divisions_map.keys())
    parent_rgb_sets = {}

    for i in range(len(div_ids)):
      local_did = div_ids[i]
      div_rec = divisions_map[local_did]
      canon_parent = str(div_rec.get("canonical_parent") or "")
      if not canon_parent:
        continue
      if canon_parent not in parent_rgb_sets:
        parent_rgb_sets[canon_parent] = set()
      div_rgbs = self.entity_rgb_lookup.get(local_did, [])
      for x in range(len(div_rgbs)):
        parent_rgb_sets[canon_parent].add(tuple(div_rgbs[x]))

    for local_parent, rgb_set in sorted(parent_rgb_sets.items()):
      self.entity_rgb_lookup[f"canonical_group:{local_parent}"] = [
        [int(t[0]), int(t[1]), int(t[2])] for t in sorted(rgb_set)
      ]

    #Return statement
    return self.entity_rgb_lookup


  def C_exportFlatJsonMaps (self, arg1_country_masks_map, arg2_subadmin_masks_map, arg3_city_masks_map, arg4_table_masks_map):
    """
    @brief Step C: Clean obsolete outputs and write country_masks.json, subadmin_masks.json, city_masks.json and table_masks.json.
    @param arg1_country_masks_map Flat dictionary mapping canonical country_key -> [[R, G, B], ...].
    @param arg2_subadmin_masks_map Flat dictionary mapping canonical subadmin_key -> [[R, G, B], ...].
    @param arg3_city_masks_map Flat dictionary mapping canonical city_key -> [lng, lat].
    @param arg4_table_masks_map Flat dictionary mapping table/series keys -> '<type>:<canonical_key>' or list thereof.
    @return Dictionary of written JSON file paths.
    """
    #Convert from parameters
    country_masks_map = arg1_country_masks_map if isinstance(arg1_country_masks_map, dict) else {}
    subadmin_masks_map = arg2_subadmin_masks_map if isinstance(arg2_subadmin_masks_map, dict) else {}
    city_masks_map = arg3_city_masks_map if isinstance(arg3_city_masks_map, dict) else {}
    table_masks_map = arg4_table_masks_map if isinstance(arg4_table_masks_map, dict) else {}

    #Declare local instance variables
    city_fname = str(self.outputs_cfg.get("city_masks_json", "city_masks.json"))
    country_fname = str(self.outputs_cfg.get("country_masks_json", "country_masks.json"))
    existing_files = []
    keep_names = set()
    p_city = ""
    p_country = ""
    p_subadmin = ""
    p_table = ""
    prov_fname = str(self.outputs_cfg.get("provinces_png", "provinces.png"))
    subadmin_fname = str(self.outputs_cfg.get("subadmin_masks_json", "subadmin_masks.json"))
    table_fname = str(self.outputs_cfg.get("table_masks_json", "table_masks.json"))
    written_paths = {}

    keep_names = {city_fname, country_fname, prov_fname, subadmin_fname, table_fname}
    existing_files = os.listdir(self.output_dir) if os.path.exists(self.output_dir) else []
    for i in range(len(existing_files)):
      fname = existing_files[i]
      if fname not in keep_names and not fname.endswith(".part"):
        fpath = os.path.join(self.output_dir, fname)
        if os.path.isfile(fpath):
          os.remove(fpath)

    p_country = os.path.join(self.output_dir, country_fname)
    p_subadmin = os.path.join(self.output_dir, subadmin_fname)
    p_city = os.path.join(self.output_dir, city_fname)
    p_table = os.path.join(self.output_dir, table_fname)

    self.writeCompactFlatJson(p_country, country_masks_map)
    self.writeCompactFlatJson(p_subadmin, subadmin_masks_map)
    self.writeCompactFlatJson(p_city, city_masks_map)
    self.writeCompactFlatJson(p_table, table_masks_map)

    written_paths["city_masks_json"] = p_city
    written_paths["country_masks_json"] = p_country
    written_paths["subadmin_masks_json"] = p_subadmin
    written_paths["table_masks_json"] = p_table

    #Return statement
    return written_paths


  def generateDistinctRgbPalette (self, arg1_count, arg2_seed):
    """
    @brief Generate deterministic, collision-free, high-contrast non-zero RGB colours ([R, G, B] != [0, 0, 0]).
    @param arg1_count Number of unique colours required.
    @param arg2_seed Integer seed controlling coprime 24-bit golden-ratio stride offset.
    @return List of [R, G, B] integer triplets.
    """
    #Convert from parameters
    count = max(0, int(arg1_count))
    seed = int(arg2_seed)

    #Declare local instance variables
    colours_array = []
    state = (seed*2654435761) & 0xFFFFFF
    step = 10368889
    used_codes = set([0])

    for _ in range(count*4 + 64):
      if len(colours_array) >= count:
        break
      state = (state + step) & 0xFFFFFF
      if state in used_codes:
        continue
      r_ch = (state >> 16) & 0xFF
      g_ch = (state >> 8) & 0xFF
      b_ch = state & 0xFF
      if max(r_ch, g_ch, b_ch) < 40:
        continue
      used_codes.add(state)
      colours_array.append([int(r_ch), int(g_ch), int(b_ch)])

    #Return statement
    return colours_array


  def partitionEquivalenceClasses (self, arg1_entities_array, arg2_png_path, arg3_seed):
    """
    @brief Partition pixels across potentially overlapping entities into exact atomic equivalence classes with certified 0 collisions.
    @param arg1_entities_array List of entity dicts with 'entity_id' and sorted 'flat_indices'.
    @param arg2_png_path Full path to write provinces.png.
    @param arg3_seed Deterministic palette and Zobrist seed.
    @return Dictionary containing province_count, entity_rgb_masks and covered_pixels.
    """
    #Convert from parameters
    entities_array = arg1_entities_array if isinstance(arg1_entities_array, list) else []
    png_path = str(arg2_png_path or "")
    seed = int(arg3_seed)

    #Declare local instance variables
    active_px = None
    deg = np.zeros(self.rasteriser.total_pixels, dtype=np.uint16)
    entity_rgb_out = {}
    flat_rgb = np.zeros((self.rasteriser.total_pixels, 3), dtype=np.uint8)
    h1 = np.zeros(self.rasteriser.total_pixels, dtype=np.uint64)
    h2 = np.zeros(self.rasteriser.total_pixels, dtype=np.uint64)
    num_ents = len(entities_array)
    palette = []
    pixel_to_zone = np.zeros(self.rasteriser.total_pixels, dtype=np.int32)
    rng = np.random.default_rng(seed)
    z1 = rng.integers(1, (1 << 63) - 1, size=max(1, num_ents), dtype=np.uint64)
    z2 = rng.integers(1, (1 << 63) - 1, size=max(1, num_ents), dtype=np.uint64)

    for i in range(num_ents):
      idx = entities_array[i]["flat_indices"]
      if idx.size > 0:
        h1[idx] ^= z1[i]
        h2[idx] ^= z2[i]
        deg[idx] += 1

    active_px = np.flatnonzero(deg > 0)
    if active_px.size == 0:
      self.rasteriser.B_exportRgbPng(flat_rgb.reshape(self.rasteriser.height, self.rasteriser.width, 3), png_path)
      return {"covered_pixels": 0, "entity_rgb_masks": entity_rgb_out, "province_count": 0}

    sig_dtype = np.dtype([("h1", "<u8"), ("h2", "<u8"), ("deg", "<u2")])
    sigs = np.empty(active_px.size, dtype=sig_dtype)
    sigs["h1"] = h1[active_px]
    sigs["h2"] = h2[active_px]
    sigs["deg"] = deg[active_px]

    unique_sigs, inv_idx = np.unique(sigs, return_inverse=True)
    num_zones = int(unique_sigs.size)
    pixel_to_zone[active_px] = inv_idx.astype(np.int32) + 1

    order = np.argsort(inv_idx, kind="mergesort")
    sorted_active_px = active_px[order]
    sorted_inv = inv_idx[order]
    zone_splits = np.flatnonzero(np.diff(sorted_inv)) + 1
    zone_pixel_arrays = np.split(sorted_active_px, zone_splits)

    palette = self.generateDistinctRgbPalette(num_zones, seed)
    zone_member_counts = np.zeros(num_zones, dtype=np.int32)

    for i in range(num_ents):
      eid = entities_array[i]["entity_id"]
      idx = entities_array[i]["flat_indices"]
      if idx.size == 0:
        entity_rgb_out[eid] = []
        continue
      z_hits = np.unique(pixel_to_zone[idx])
      rgb_tuples = []
      for x in range(z_hits.size):
        zi = int(z_hits[x]) - 1
        if zi >= 0:
          zone_member_counts[zi] += 1
          rgb_c = palette[zi]
          rgb_tuples.append((int(rgb_c[0]), int(rgb_c[1]), int(rgb_c[2])))
      rgb_tuples.sort()
      entity_rgb_out[eid] = [[t[0], t[1], t[2]] for t in rgb_tuples]

    for i in range(num_zones):
      expected_d = int(unique_sigs[i]["deg"])
      if int(zone_member_counts[i]) != expected_d:
        sys.stderr.write(f"Console error: Zobrist degree mismatch on zone {i + 1}: {zone_member_counts[i]} != {expected_d}\n")
      z_px = zone_pixel_arrays[i]
      rgb_c = palette[i]
      flat_rgb[z_px, 0] = rgb_c[0]
      flat_rgb[z_px, 1] = rgb_c[1]
      flat_rgb[z_px, 2] = rgb_c[2]

    self.rasteriser.B_exportRgbPng(flat_rgb.reshape(self.rasteriser.height, self.rasteriser.width, 3), png_path)

    #Return statement
    return {
      "covered_pixels": int(active_px.size),
      "entity_rgb_masks": entity_rgb_out,
      "province_count": num_zones
    }


  def writeCompactFlatJson (self, arg1_path, arg2_flat_map):
    """
    @brief Serialise a flat key -> value JSON dictionary atomically with one 2-space indented entry per line.
    @param arg1_path Destination JSON file path.
    @param arg2_flat_map Flat dictionary mapping string keys to [lng, lat], target strings or [[R, G, B], ...] lists.
    """
    #Convert from parameters
    path = str(arg1_path or "")
    flat_map = arg2_flat_map if isinstance(arg2_flat_map, dict) else {}

    #Declare local instance variables
    keys_sorted = sorted(flat_map.keys())
    lines_array = ["{"]
    num_keys = len(keys_sorted)
    tmp_path = f"{path}.part"

    if not path:
      return

    try:
      for i in range(num_keys):
        local_k = keys_sorted[i]
        comma = "," if i + 1 < num_keys else ""
        k_str = orjson.dumps(local_k).decode("utf-8")
        v_str = orjson.dumps(flat_map[local_k]).decode("utf-8").replace(",", ", ")
        lines_array.append(f"  {k_str}: {v_str}{comma}")
      lines_array.append("}\n")

      os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
      with open(tmp_path, "wb") as local_fh:
        local_fh.write("\n".join(lines_array).encode("utf-8"))
      os.replace(tmp_path, path)
    except Exception as local_err:
      sys.stderr.write(f"Console error: failed writing flat JSON {path}: {local_err}\n")

