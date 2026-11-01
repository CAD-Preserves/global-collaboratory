"""@brief End-to-end orchestrator for the Global Collaboratory WGS84 Equirectangular areal mask pipeline."""

import glob
import os
import sys
import time
import numpy as np
import orjson
from PIL import Image

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
  sys.path.insert(0, REPO_ROOT)

from core.server.AdminDivisionMaskResolver import AdminDivisionMaskResolver
from core.server.CityMaskResolver import CityMaskResolver
from core.server.ConfigLoader import ConfigLoader
from core.server.CountryMaskResolver import CountryMaskResolver
from core.server.EquirectangularRasteriser import EquirectangularRasteriser
from core.server.GeoJsonFetcher import GeoJsonFetcher
from core.server.ProvinceMapSynthesizer import ProvinceMapSynthesizer


class ArealMaskGenerator:
  """@brief Orchestrates geospatial fetching, scanline rasterisation, topological snapping, Zobrist partitioning and Collaboratory table mapping."""

  def __init__ (self, arg1_root_dir=None, arg2_options=None):
    """
    @brief Initialise ArealMaskGenerator with repository root and optional configuration overrides.
    @param arg1_root_dir Optional repository root path.
    @param arg2_options Optional dictionary overriding locale or config_subdir.
    """
    #Convert from parameters
    root_dir = arg1_root_dir
    options = arg2_options if isinstance(arg2_options, dict) else {}

    #Initialise options
    if "config_subdir" not in options:
      options["config_subdir"] = os.path.join("common", "areal_masks")
    if "locale" not in options:
      options["locale"] = "en_gb"

    #Declare local instance variables
    self.admin_resolver = None
    self.admin_rules_obj = {}
    self.city_masks_map = {}
    self.city_resolver = None
    self.city_rules_obj = {}
    self.config_loader = ConfigLoader(root_dir, options)
    self.config_subdir = str(options["config_subdir"])
    self.country_masks_map = {}
    self.country_resolver = None
    self.country_rules_obj = {}
    self.fetcher = None
    self.rasteriser = None
    self.resolved_countries_map = {}
    self.resolved_divisions_map = {}
    self.resolved_groups_map = {}
    self.root_dir = self.config_loader.root_dir
    self.subadmin_masks_map = {}
    self.synthesizer = None
    self.table_masks_map = {}
    self.table_rules_obj = {}
    self.unaccounted_items = []

    areal_cfg = self.config_loader.areal_config_obj
    self.fetcher = GeoJsonFetcher(self.root_dir, areal_cfg)
    self.rasteriser = EquirectangularRasteriser(
      areal_cfg.get("grid", {}),
      areal_cfg.get("frontier_snap", {})
    )
    self.synthesizer = ProvinceMapSynthesizer(self.root_dir, areal_cfg, self.rasteriser)


  def A_resolveCanonicalGeographies (self):
    """
    @brief Step A: Load declarative rule files from /common/areal_masks/ and resolve all country, city and subadministrative masks.
    @return Dictionary summarising resolved country, subadmin and city counts.
    """
    #Declare local instance variables
    admin_res = {}
    cfg_dir = os.path.join(self.root_dir, self.config_subdir)

    self.country_rules_obj = self.config_loader.loadJson5File(os.path.join(cfg_dir, "country_rules.json5"))
    self.admin_rules_obj = self.config_loader.loadJson5File(os.path.join(cfg_dir, "admin_division_rules.json5"))
    self.city_rules_obj = self.config_loader.loadJson5File(os.path.join(cfg_dir, "city_rules.json5"))
    self.table_rules_obj = self.config_loader.loadJson5File(os.path.join(cfg_dir, "table_rules.json5"))

    self.country_resolver = CountryMaskResolver(self.fetcher, self.rasteriser, self.country_rules_obj)
    self.resolved_countries_map = self.country_resolver.A_resolveAllCountries()
    print(self.config_loader.formatLocalisedString("masks_countries_resolved", [len(self.resolved_countries_map)]))

    self.city_resolver = CityMaskResolver(self.fetcher, self.city_rules_obj)
    self.city_masks_map = self.city_resolver.A_resolveAllCities()
    print(self.config_loader.formatLocalisedString("masks_cities_resolved", [len(self.city_masks_map)]))

    self.admin_resolver = AdminDivisionMaskResolver(
      self.fetcher,
      self.rasteriser,
      self.country_resolver,
      self.city_resolver,
      self.admin_rules_obj
    )
    admin_res = self.admin_resolver.A_resolveAllAdminDivisions()
    self.resolved_divisions_map = admin_res["divisions"]
    self.resolved_groups_map = admin_res["groups"]
    print(self.config_loader.formatLocalisedString("masks_divisions_resolved", [len(self.resolved_divisions_map), len(self.admin_resolver.partition_sets_cfg)]))

    #Return statement
    return {
      "cities": len(self.city_masks_map),
      "countries": len(self.resolved_countries_map),
      "divisions": len(self.resolved_divisions_map)
    }


  def B_synthesiseProvinceRaster (self):
    """
    @brief Step B: Synthesise provinces.png via double-64-bit Zobrist hashing and assemble country_masks_map and subadmin_masks_map.
    @return Dictionary containing province_count, covered_pixels and png_path.
    """
    #Declare local instance variables
    div_rgb_sets = {}
    rgb_lookup = {}
    synth_info = {}

    synth_info = self.synthesizer.A_synthesiseProvincesPng(self.resolved_countries_map, self.resolved_divisions_map)
    rgb_lookup = self.synthesizer.B_registerAdminGroupMasks(self.resolved_divisions_map)
    print(self.config_loader.formatLocalisedString("masks_synthesised", [synth_info["province_count"], synth_info["covered_pixels"]]))

    self.country_masks_map = {}
    self.subadmin_masks_map = {}

    for local_cid in sorted(self.resolved_countries_map.keys()):
      local_rgbs = rgb_lookup.get(local_cid, [])
      if self.country_resolver.isSubadminEntity(local_cid):
        self.subadmin_masks_map[local_cid] = local_rgbs
      else:
        self.country_masks_map[local_cid] = local_rgbs

    for local_did, div_rec in sorted(self.resolved_divisions_map.items()):
      ckey = str(div_rec.get("canonical_key") or "")
      if not ckey:
        continue
      div_rgbs = rgb_lookup.get(local_did, [])
      for i in range(len(div_rgbs)):
        div_rgb_sets.setdefault(ckey, set()).add(tuple(div_rgbs[i]))

    for local_ck, rgb_set in sorted(div_rgb_sets.items()):
      self.subadmin_masks_map[local_ck] = [[int(t[0]), int(t[1]), int(t[2])] for t in sorted(rgb_set)]

    for local_parent in sorted(self.resolved_groups_map.keys()):
      if local_parent not in self.subadmin_masks_map:
        grp_rgbs = rgb_lookup.get(f"canonical_group:{local_parent}", [])
        if grp_rgbs:
          self.subadmin_masks_map[local_parent] = grp_rgbs

    #Return statement
    return synth_info


  def C_mapCollaboratoryTables (self):
    """
    @brief Step C: Scan all 98 raw_tables and sectoral_harmonised JSON files and map every dataset and sub-table series to its canonical mask.
    @return Flat table_masks_map dictionary.
    """
    #Declare local instance variables
    country_series_cfg = self.table_rules_obj.get("country_series", {})
    dataset_countries_cfg = self.table_rules_obj.get("dataset_countries", {})
    dataset_localities_cfg = self.table_rules_obj.get("dataset_localities", {})
    dataset_regions_cfg = self.table_rules_obj.get("dataset_regions", {})
    datasets_cfg = self.table_rules_obj.get("datasets", {})
    harm_dir = os.path.join(self.root_dir, str(self.config_loader.areal_config_obj.get("paths", {}).get("harmonised_json_dir", "output/json/sectoral_harmonised")))
    harm_files = sorted(glob.glob(os.path.join(harm_dir, "*.json")))
    locality_series_cfg = self.table_rules_obj.get("locality_series", {})
    raw_dir = os.path.join(self.root_dir, str(self.config_loader.areal_config_obj.get("paths", {}).get("raw_json_dir", "output/json/raw_tables")))
    raw_files = sorted(glob.glob(os.path.join(raw_dir, "*.json")))
    region_series_cfg = self.table_rules_obj.get("region_series", {})
    stems_map = {}

    self.table_masks_map = {}
    self.unaccounted_items = []

    for i in range(len(raw_files)):
      local_fn = os.path.basename(raw_files[i])
      local_stem = os.path.splitext(local_fn)[0]
      stems_map.setdefault(local_stem, {})["raw_path"] = raw_files[i]

    for i in range(len(harm_files)):
      local_fn = os.path.basename(harm_files[i])
      local_stem = os.path.splitext(local_fn)[0]
      stems_map.setdefault(local_stem, {})["harm_path"] = harm_files[i]

    for local_stem in sorted(stems_map.keys()):
      local_info = stems_map[local_stem]
      local_fn = f"{local_stem}.json"
      ds_target = datasets_cfg.get(local_stem) or datasets_cfg.get(local_fn)

      if ds_target is None or not self.isValidMaskTarget(ds_target):
        sys.stderr.write(f"Console error: unaccounted or invalid dataset target for '{local_stem}': {ds_target}\n")
        self.unaccounted_items.append(f"dataset:{local_stem}")
        continue

      norm_ds_target = self.normaliseTargetSpec(ds_target)
      self.table_masks_map[local_fn] = norm_ds_target
      self.table_masks_map[local_stem] = norm_ds_target
      if "raw_path" in local_info:
        self.table_masks_map[f"raw_tables/{local_stem}"] = norm_ds_target
      if "harm_path" in local_info:
        self.table_masks_map[f"sectoral_harmonised/{local_stem}"] = norm_ds_target

      if "raw_path" in local_info:
        sub_meta = self.extractRawTableSubEntities(local_info["raw_path"])

        if len(sub_meta["countries"]) > 1:
          for x in range(len(sub_meta["countries"])):
            c_slug = self.fetcher.normaliseAsciiSlug(sub_meta["countries"][x])
            if not c_slug:
              continue
            c_target = (
              dataset_countries_cfg.get(f"{local_stem}::{c_slug}")
              or country_series_cfg.get(c_slug)
            )
            if c_target is None:
              alias_cid = self.country_resolver.B_resolveCountryAlias(c_slug)
              if alias_cid:
                c_target = self.country_resolver.formatEntityMaskRef(alias_cid)
            if c_target is not None and self.isValidMaskTarget(c_target):
              self.table_masks_map[f"{local_stem}.country:{c_slug}"] = self.normaliseTargetSpec(c_target)
            else:
              sys.stderr.write(f"Console error: unaccounted multi-country series '{local_stem}.country:{c_slug}'\n")
              self.unaccounted_items.append(f"{local_stem}.country:{c_slug}")

        for x in range(len(sub_meta["regions"])):
          r_slug = self.fetcher.normaliseAsciiSlug(sub_meta["regions"][x])
          if not r_slug:
            continue
          r_target = (
            dataset_regions_cfg.get(f"{local_stem}::{r_slug}")
            or region_series_cfg.get(r_slug)
          )
          if r_target is not None and self.isValidMaskTarget(r_target):
            self.table_masks_map[f"{local_stem}.region:{r_slug}"] = self.normaliseTargetSpec(r_target)
          else:
            sys.stderr.write(f"Console error: unaccounted region series '{local_stem}.region:{r_slug}' (raw='{sub_meta['regions'][x]}')\n")
            self.unaccounted_items.append(f"{local_stem}.region:{r_slug}")

        for x in range(len(sub_meta["localities"])):
          l_slug = self.fetcher.normaliseAsciiSlug(sub_meta["localities"][x])
          if not l_slug:
            continue
          l_target = (
            dataset_localities_cfg.get(f"{local_stem}::{l_slug}")
            or locality_series_cfg.get(l_slug)
          )
          if l_target is None:
            cand_city = self.city_resolver.normaliseCityKey(l_slug)
            if cand_city in self.city_masks_map:
              l_target = f"city:{cand_city}"
          if l_target is not None and self.isValidMaskTarget(l_target):
            self.table_masks_map[f"{local_stem}.locality:{l_slug}"] = self.normaliseTargetSpec(l_target)
          else:
            sys.stderr.write(f"Console error: unaccounted locality series '{local_stem}.locality:{l_slug}' (raw='{sub_meta['localities'][x]}')\n")
            self.unaccounted_items.append(f"{local_stem}.locality:{l_slug}")

    print(self.config_loader.formatLocalisedString("masks_table_lookup_exported", [len(self.table_masks_map)]))

    #Return statement
    return self.table_masks_map


  def D_exportDeliverables (self):
    """
    @brief Step D: Write country_masks.json, subadmin_masks.json, city_masks.json and table_masks.json to output/areal_masks/.
    @return Dictionary of written deliverable file paths.
    """
    #Return statement
    return self.synthesizer.C_exportFlatJsonMaps(
      self.country_masks_map,
      self.subadmin_masks_map,
      self.city_masks_map,
      self.table_masks_map
    )


  def E_verifyDeliverablesOnDisk (self):
    """
    @brief Step E: Reload all 5 deliverables from disk and verify 100% RGB, coordinate and table-reference integrity.
    @return Boolean True when all verification checks pass with zero errors.
    """
    #Declare local instance variables
    active_rgb_codes = None
    all_referenced_codes = set()
    city_json = {}
    country_json = {}
    ok_flag = True
    out_dir = self.synthesizer.output_dir
    outputs_cfg = self.synthesizer.outputs_cfg
    png_arr = None
    png_path = os.path.join(out_dir, str(outputs_cfg.get("provinces_png", "provinces.png")))
    present_code_set = set()
    subadmin_json = {}
    table_json = {}

    if not os.path.exists(png_path):
      sys.stderr.write(f"Console error: missing provinces.png at {png_path}\n")
      return False

    png_arr = np.asarray(Image.open(png_path))
    if png_arr.shape != (self.rasteriser.height, self.rasteriser.width, 3):
      sys.stderr.write(f"Console error: invalid provinces.png dimensions {png_arr.shape}\n")
      ok_flag = False

    packed = (
      (png_arr[:, :, 0].astype(np.uint32) << 16)
      | (png_arr[:, :, 1].astype(np.uint32) << 8)
      | png_arr[:, :, 2].astype(np.uint32)
    )
    active_rgb_codes = np.unique(packed[packed > 0])
    present_code_set = set(int(c) for c in active_rgb_codes)

    country_json = orjson.loads(open(os.path.join(out_dir, str(outputs_cfg.get("country_masks_json", "country_masks.json"))), "rb").read())
    subadmin_json = orjson.loads(open(os.path.join(out_dir, str(outputs_cfg.get("subadmin_masks_json", "subadmin_masks.json"))), "rb").read())
    city_json = orjson.loads(open(os.path.join(out_dir, str(outputs_cfg.get("city_masks_json", "city_masks.json"))), "rb").read())
    table_json = orjson.loads(open(os.path.join(out_dir, str(outputs_cfg.get("table_masks_json", "table_masks.json"))), "rb").read())

    for local_map_name, local_map in (("country_masks.json", country_json), ("subadmin_masks.json", subadmin_json)):
      for local_k, rgb_list in local_map.items():
        if not isinstance(rgb_list, list) or len(rgb_list) == 0:
          sys.stderr.write(f"Console error: empty RGB mask for '{local_k}' in {local_map_name}\n")
          ok_flag = False
          continue
        for x in range(len(rgb_list)):
          c_trip = rgb_list[x]
          c_int = (int(c_trip[0]) << 16) | (int(c_trip[1]) << 8) | int(c_trip[2])
          all_referenced_codes.add(c_int)
          if c_int == 0 or c_int not in present_code_set:
            sys.stderr.write(f"Console error: RGB {c_trip} in {local_map_name}:{local_k} missing from provinces.png\n")
            ok_flag = False

    if present_code_set != all_referenced_codes:
      orphan_count = len(present_code_set - all_referenced_codes)
      sys.stderr.write(f"Console error: {orphan_count} orphan RGB colourcodes on provinces.png\n")
      ok_flag = False

    for local_ck, coords in city_json.items():
      if (
        not isinstance(coords, list)
        or len(coords) != 2
        or not (-180.0 <= float(coords[0]) <= 180.0)
        or not (-90.0 <= float(coords[1]) <= 90.0)
      ):
        sys.stderr.write(f"Console error: invalid city coordinates for '{local_ck}': {coords}\n")
        ok_flag = False

    for local_tk, t_spec in table_json.items():
      targets_list = t_spec if isinstance(t_spec, list) else [t_spec]
      if not targets_list:
        ok_flag = False
      for x in range(len(targets_list)):
        t_str = str(targets_list[x])
        if t_str.startswith("country:"):
          if t_str[8:] not in country_json:
            sys.stderr.write(f"Console error: table_masks '{local_tk}' references missing {t_str}\n")
            ok_flag = False
        elif t_str.startswith("subadmin:"):
          if t_str[9:] not in subadmin_json:
            sys.stderr.write(f"Console error: table_masks '{local_tk}' references missing {t_str}\n")
            ok_flag = False
        elif t_str.startswith("city:"):
          if t_str[5:] not in city_json:
            sys.stderr.write(f"Console error: table_masks '{local_tk}' references missing {t_str}\n")
            ok_flag = False
        else:
          sys.stderr.write(f"Console error: invalid prefix in table_masks '{local_tk}': {t_str}\n")
          ok_flag = False

    if self.unaccounted_items:
      ok_flag = False

    #Return statement
    return ok_flag


  def extractRawTableSubEntities (self, arg1_raw_json_path):
    """
    @brief Scan a raw Collaboratory table JSON file and extract sorted non-NA Country, Region and Locality values.
    @param arg1_raw_json_path Path to raw_tables/<stem>.json.
    @return Dictionary containing 'countries', 'regions' and 'localities' sorted string lists.
    """
    #Convert from parameters
    raw_json_path = str(arg1_raw_json_path or "")

    #Declare local instance variables
    countries_set = set()
    data_obj = None
    ignore_tokens = {"", "-1", "NA", "N/A", "NONE", "NULL"}
    locs_set = set()
    regions_set = set()
    rows_iter = []

    if not raw_json_path or not os.path.exists(raw_json_path):
      return {"countries": [], "localities": [], "regions": []}

    try:
      with open(raw_json_path, "rb") as local_fh:
        data_obj = orjson.loads(local_fh.read())
    except Exception as local_err:
      sys.stderr.write(f"Console error: failed reading raw table {raw_json_path}: {local_err}\n")
      return {"countries": [], "localities": [], "regions": []}

    rows_iter = list(data_obj.values()) if isinstance(data_obj, dict) else (data_obj if isinstance(data_obj, list) else [])
    for i in range(len(rows_iter)):
      local_r = rows_iter[i]
      if not isinstance(local_r, dict):
        continue
      c_val = str(local_r.get("Country") or "").strip()
      r_val = str(local_r.get("Region") or "").strip()
      l_val = str(local_r.get("Locality") or "").strip()
      if c_val.upper() not in ignore_tokens:
        countries_set.add(c_val)
      if r_val.upper() not in ignore_tokens:
        regions_set.add(r_val)
      if l_val.upper() not in ignore_tokens:
        locs_set.add(l_val)

    #Return statement
    return {
      "countries": sorted(countries_set),
      "localities": sorted(locs_set),
      "regions": sorted(regions_set)
    }


  def isValidMaskTarget (self, arg1_target_spec):
    """
    @brief Validate that a single 'type:id' target string or list of target strings exists in the resolved mask dictionaries.
    @param arg1_target_spec String or list of strings.
    @return Boolean True if every target resolves to a valid non-empty mask or city coordinate.
    """
    #Convert from parameters
    target_spec = arg1_target_spec

    #Declare local instance variables
    items_list = []

    if isinstance(target_spec, str):
      items_list = [target_spec]
    elif isinstance(target_spec, list) and len(target_spec) > 0:
      items_list = target_spec
    else:
      return False

    for i in range(len(items_list)):
      t_str = str(items_list[i] or "").strip()
      if t_str.startswith("country:"):
        cid = t_str[8:]
        if cid not in self.country_masks_map or len(self.country_masks_map[cid]) == 0:
          return False
      elif t_str.startswith("subadmin:"):
        sid = t_str[9:]
        if sid not in self.subadmin_masks_map or len(self.subadmin_masks_map[sid]) == 0:
          return False
      elif t_str.startswith("city:"):
        city_id = t_str[5:]
        if city_id not in self.city_masks_map:
          return False
      else:
        return False

    #Return statement
    return True


  def normaliseTargetSpec (self, arg1_target_spec):
    """
    @brief Normalise a target specification into a trimmed string or sorted deduplicated list of strings.
    @param arg1_target_spec String or list of target strings.
    @return String (if 1 element) or sorted list of strings.
    """
    #Convert from parameters
    target_spec = arg1_target_spec

    #Declare local instance variables
    cleaned_list = []

    if isinstance(target_spec, str):
      return target_spec.strip()
    if isinstance(target_spec, list):
      cleaned_list = sorted(set(str(x).strip() for x in target_spec if str(x).strip()))
      if len(cleaned_list) == 1:
        return cleaned_list[0]
      return cleaned_list

    #Return statement
    return ""


  def runPipeline (self):
    """
    @brief Execute Steps A through E of the Global Collaboratory areal mask pipeline and report elapsed wall-clock time.
    @return Boolean True when all deliverables are generated and verified with zero errors.
    """
    #Declare local instance variables
    elapsed_sec = 0.0
    ok_status = False
    t_start = time.time()

    print(self.config_loader.formatLocalisedString(
      "masks_initialised",
      [self.rasteriser.width, self.rasteriser.height, self.rasteriser.crs]
    ))
    self.A_resolveCanonicalGeographies()
    self.B_synthesiseProvinceRaster()
    self.C_mapCollaboratoryTables()
    self.D_exportDeliverables()
    ok_status = self.E_verifyDeliverablesOnDisk()
    elapsed_sec = round(time.time() - t_start, 2)
    ds_count = len([k for k in self.table_masks_map.keys() if k.endswith(".json")])
    sub_count = len([k for k in self.table_masks_map.keys() if ".region:" in k or ".locality:" in k or ".country:" in k])
    print(self.config_loader.formatLocalisedString(
      "masks_verified_done",
      [ds_count, ds_count + len([x for x in self.unaccounted_items if x.startswith("dataset:")]), sub_count, len(self.unaccounted_items), elapsed_sec]
    ))

    #Return statement
    return ok_status


if __name__ == "__main__":
  pipeline_obj = ArealMaskGenerator()
  if not pipeline_obj.runPipeline():
    sys.exit(1)
