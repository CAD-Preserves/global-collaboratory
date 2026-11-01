"""@brief Resolves modern, colonial and historical whole-country areal masks (1495-2025) from Natural Earth, GADM, British India 1948, Russia 1897 and Phersu layers."""

import sys
import numpy as np


class CountryMaskResolver:
  """@brief Resolves canonical country definitions and sub-imperial territories onto the 4320x2160 Equirectangular grid."""

  def __init__ (self, arg1_fetcher, arg2_rasteriser, arg3_country_rules_obj):
    """
    @brief Initialise CountryMaskResolver with GeoJsonFetcher, EquirectangularRasteriser and parsed country_rules.json5.
    @param arg1_fetcher GeoJsonFetcher instance.
    @param arg2_rasteriser EquirectangularRasteriser instance.
    @param arg3_country_rules_obj Parsed country_rules.json5 dictionary.
    """
    #Convert from parameters
    fetcher = arg1_fetcher
    rasteriser = arg2_rasteriser
    country_rules_obj = arg3_country_rules_obj if isinstance(arg3_country_rules_obj, dict) else {}

    #Declare local instance variables
    self.aliases_cfg = country_rules_obj.get("aliases", {})
    self.countries_cfg = country_rules_obj.get("countries", {})
    self.fetcher = fetcher
    self.landmask_indices = None
    self.rasteriser = rasteriser
    self.resolved_countries_obj = {}
    self.subadmin_entities_set = set(country_rules_obj.get("subadmin_entities", []))


  def A_resolveAllCountries (self):
    """
    @brief Step A: Rasterise all canonical modern, colonial and historical country entities onto the 4320x2160 grid.
    @return Dictionary mapping canonical country_id -> resolved entity record with flat_indices and metrics.
    """
    #Declare local instance variables
    all_country_ids = sorted(self.countries_cfg.keys())

    for i in range(len(all_country_ids)):
      local_cid = all_country_ids[i]
      self.resolveSingleCountry(local_cid, set())

    #Return statement
    return self.resolved_countries_obj


  def B_resolveCountryAlias (self, arg1_raw_name):
    """
    @brief Step B: Resolve a raw country label or slug to a canonical country/subadmin entity ID if configured.
    @param arg1_raw_name Raw country label or snake_case key.
    @return Canonical entity ID string or empty string if unrecognised.
    """
    #Convert from parameters
    raw_name = str(arg1_raw_name or "").strip()

    #Declare local instance variables
    slug = self.fetcher.normaliseAsciiSlug(raw_name)

    if not slug:
      return ""
    if slug in self.countries_cfg:
      return slug
    if slug in self.aliases_cfg:
      target_id = str(self.aliases_cfg[slug] or "").strip()
      if target_id in self.countries_cfg:
        return target_id

    #Return statement
    return ""


  def applySourceModifiers (self, arg1_flat_indices, arg2_source_obj, arg3_visiting_set):
    """
    @brief Apply declarative admin1/GADM/layer unions, subtractions, landmask clips, topological host snapping and country exclusions.
    @param arg1_flat_indices Initial sorted 1D int32 array of flat pixel indices.
    @param arg2_source_obj Country source specification dictionary.
    @param arg3_visiting_set Set of currently visiting country IDs to prevent cyclic recursion.
    @return Modified sorted 1D int32 array of flat pixel indices.
    """
    #Convert from parameters
    flat_indices = arg1_flat_indices
    source_obj = arg2_source_obj if isinstance(arg2_source_obj, dict) else {}
    visiting_set = arg3_visiting_set if isinstance(arg3_visiting_set, set) else set()

    #Declare local instance variables
    clip_countries = source_obj.get("clip_to", [])
    clip_parts = None
    exclude_countries = source_obj.get("exclude_countries", [])
    extra_admin1 = source_obj.get("extra_admin1", [])
    extra_gadm = source_obj.get("extra_gadm", [])
    extra_layers = source_obj.get("extra_layers", [])
    extra_members = source_obj.get("extra_members", [])
    inter_coords = source_obj.get("intersect_coords", [])
    layer_key = str(source_obj.get("layer") or "")
    non_ne_layers = {
      "british_india_1948", "gadm", "galicia_habsburg", "germany_1914",
      "phersu", "russia_1897", "uk_counties", "uk_historic_counties"
    }
    parts_list = []
    should_snap = False
    sub_admin1 = source_obj.get("subtract_admin1", [])
    sub_gadm = source_obj.get("subtract_gadm", [])

    if isinstance(extra_admin1, list) and extra_admin1:
      parts_list = [flat_indices] if flat_indices.size > 0 else []
      for i in range(len(extra_admin1)):
        local_feats = self.matchAdmin1Features(extra_admin1[i])
        local_idx = self.rasteriser.A_rasteriseGeometry(local_feats, {"ensure_min_pixel": False})
        if local_idx.size > 0:
          parts_list.append(local_idx)
      flat_indices = np.unique(np.concatenate(parts_list)) if parts_list else flat_indices

    if isinstance(extra_gadm, list) and extra_gadm:
      parts_list = [flat_indices] if flat_indices.size > 0 else []
      for i in range(len(extra_gadm)):
        local_g = extra_gadm[i]
        local_feats = self.matchGadmSubset(
          str(local_g.get("gadm_iso3") or ""),
          int(local_g.get("gadm_level") or 1),
          local_g.get("names", []),
          local_g.get("names_1", []),
          local_g.get("names_2", [])
        )
        local_idx = self.rasteriser.A_rasteriseGeometry(local_feats, {"ensure_min_pixel": False})
        if local_g.get("clip_to"):
          local_clip = self.collectCountryUnionIndices(local_g["clip_to"], visiting_set)
          if local_g.get("snap_to_host", True):
            local_idx = self.rasteriser.snapHistoricalFrontierToHost(local_idx, local_clip, local_g.get("snap_options"))
          else:
            local_idx = self.rasteriser.clipIndicesWithFallback(local_idx, local_clip)
        if local_idx.size > 0:
          parts_list.append(local_idx)
      flat_indices = np.unique(np.concatenate(parts_list)) if parts_list else flat_indices

    if isinstance(extra_layers, list) and extra_layers:
      parts_list = [flat_indices] if flat_indices.size > 0 else []
      for i in range(len(extra_layers)):
        local_l = extra_layers[i]
        local_lk = str(local_l.get("layer") or "")
        if local_l.get("type") == "polygon":
          local_poly = {"coordinates": [local_l.get("coords", [])], "type": "Polygon"}
          local_idx = self.rasteriser.A_rasteriseGeometry(local_poly, {"ensure_min_pixel": False})
        elif local_lk in ("ne_admin0", "ne_map_units", "ne_subunits"):
          local_feats = self.matchAdmin0Features(local_lk, local_l)
          local_idx = self.rasteriser.A_rasteriseGeometry(local_feats, {"ensure_min_pixel": False})
        elif local_lk == "ne_admin1":
          local_feats = self.matchAdmin1Features(local_l)
          local_idx = self.rasteriser.A_rasteriseGeometry(local_feats, {"ensure_min_pixel": False})
        elif local_lk == "british_india_1948":
          local_feats = self.matchBritishIndiaFeatures(local_l)
          local_idx = self.rasteriser.A_rasteriseGeometry(local_feats, {"ensure_min_pixel": False})
        elif local_lk == "russia_1897":
          local_feats = self.matchRussia1897Features(local_l)
          local_idx = self.rasteriser.A_rasteriseGeometry(local_feats, {"ensure_min_pixel": False})
        elif local_lk == "phersu":
          local_feats = self.matchPhersuFeatures(local_l)
          local_idx = self.rasteriser.A_rasteriseGeometry(local_feats, {"ensure_min_pixel": False})
        elif local_lk == "gadm":
          local_feats = self.matchGadmSubset(
            str(local_l.get("gadm_iso3") or ""),
            int(local_l.get("gadm_level") or 1),
            local_l.get("names", []),
            local_l.get("names_1", []),
            local_l.get("names_2", [])
          )
          local_idx = self.rasteriser.A_rasteriseGeometry(local_feats, {"ensure_min_pixel": False})
        else:
          local_feats = self.matchHistoricalBasemapFeatures(local_lk, local_l)
          local_idx = self.rasteriser.A_rasteriseGeometry(local_feats, {"ensure_min_pixel": False})
        local_idx = self.applySourceModifiers(local_idx, local_l, visiting_set)
        if local_idx.size > 0:
          parts_list.append(local_idx)
      flat_indices = np.unique(np.concatenate(parts_list)) if parts_list else flat_indices

    if isinstance(inter_coords, list) and len(inter_coords) >= 4:
      poly_geom = {"coordinates": [inter_coords], "type": "Polygon"}
      inter_idx = self.rasteriser.A_rasteriseGeometry(poly_geom, {"ensure_min_pixel": False})
      flat_indices = self.rasteriser.clipIndicesWithFallback(flat_indices, inter_idx)

    if isinstance(sub_admin1, list) and sub_admin1:
      for i in range(len(sub_admin1)):
        local_feats = self.matchAdmin1Features(sub_admin1[i])
        local_sub = self.rasteriser.A_rasteriseGeometry(local_feats, {"ensure_min_pixel": False})
        if local_sub.size > 0 and flat_indices.size > 0:
          flat_indices = np.setdiff1d(flat_indices, local_sub, assume_unique=True)

    if isinstance(sub_gadm, list) and sub_gadm:
      for i in range(len(sub_gadm)):
        local_g = sub_gadm[i]
        local_feats = self.matchGadmSubset(
          str(local_g.get("gadm_iso3") or ""),
          int(local_g.get("gadm_level") or 1),
          local_g.get("names", []),
          local_g.get("names_1", []),
          local_g.get("names_2", [])
        )
        local_sub = self.rasteriser.A_rasteriseGeometry(local_feats, {"ensure_min_pixel": False})
        if local_sub.size > 0 and flat_indices.size > 0:
          if local_g.get("snap_to_host", False):
            local_sub = self.rasteriser.snapHistoricalFrontierToHost(local_sub, flat_indices, local_g.get("snap_options"))
          flat_indices = np.setdiff1d(flat_indices, local_sub, assume_unique=True)

    if isinstance(extra_members, list) and extra_members:
      parts_list = [flat_indices] if flat_indices.size > 0 else []
      for i in range(len(extra_members)):
        local_ex = self.resolveSingleCountry(str(extra_members[i]), visiting_set)
        if local_ex["flat_indices"].size > 0:
          parts_list.append(local_ex["flat_indices"])
      flat_indices = np.unique(np.concatenate(parts_list)) if parts_list else flat_indices

    if layer_key in non_ne_layers and not source_obj.get("do_not_clip_land"):
      flat_indices = self.rasteriser.clipIndicesWithFallback(flat_indices, self.getLandmaskIndices())

    if isinstance(clip_countries, list) and clip_countries:
      clip_parts = self.collectCountryUnionIndices(clip_countries, visiting_set)
      if clip_parts.size > 0:
        should_snap = bool(source_obj.get("snap_to_host", layer_key == "phersu")) and not bool(source_obj.get("do_not_snap_to_host", False))
        if should_snap:
          flat_indices = self.rasteriser.snapHistoricalFrontierToHost(flat_indices, clip_parts, source_obj.get("snap_options"))
        else:
          flat_indices = self.rasteriser.clipIndicesWithFallback(flat_indices, clip_parts)

    if isinstance(exclude_countries, list) and exclude_countries:
      excl_idx = self.collectCountryUnionIndices(exclude_countries, visiting_set)
      if excl_idx.size > 0 and flat_indices.size > 0:
        reduced = np.setdiff1d(flat_indices, excl_idx, assume_unique=True)
        if reduced.size > 0:
          flat_indices = reduced

    #Return statement
    return flat_indices


  def collectCountryUnionIndices (self, arg1_country_ids_list, arg2_visiting_set):
    """
    @brief Resolve and union flat pixel index arrays across a list of canonical country IDs.
    @param arg1_country_ids_list List of canonical country IDs.
    @param arg2_visiting_set Active recursion guard set.
    @return Sorted 1D int32 array of unioned pixel indices.
    """
    #Convert from parameters
    country_ids_list = arg1_country_ids_list if isinstance(arg1_country_ids_list, list) else []
    visiting_set = arg2_visiting_set if isinstance(arg2_visiting_set, set) else set()

    #Declare local instance variables
    arrays_list = []

    for i in range(len(country_ids_list)):
      local_cid = str(country_ids_list[i] or "").strip()
      if local_cid and local_cid not in visiting_set:
        local_rec = self.resolveSingleCountry(local_cid, set(visiting_set))
        if local_rec["flat_indices"].size > 0:
          arrays_list.append(local_rec["flat_indices"])

    #Return statement
    return np.unique(np.concatenate(arrays_list)) if arrays_list else np.zeros(0, dtype=np.int32)


  def formatEntityMaskRef (self, arg1_entity_id):
    """
    @brief Format a canonical country/subadmin entity ID into a 'type:key' reference for table_masks.json.
    @param arg1_entity_id Canonical entity ID in country_rules.json5.
    @return String 'subadmin:<entity_id>' or 'country:<entity_id>'.
    """
    #Convert from parameters
    entity_id = str(arg1_entity_id or "").strip()

    #Declare local instance variables
    prefix_str = "subadmin" if self.isSubadminEntity(entity_id) else "country"

    #Return statement
    return f"{prefix_str}:{entity_id}"


  def getLandmaskIndices (self):
    """
    @brief Build and cache the canonical 4320x2160 10m Natural Earth landmask excluding Antarctica (ATA).
    @return Sorted 1D numpy int32 array of global non-Antarctic terrestrial pixel indices.
    """
    #Declare local instance variables
    adm0_feats = []
    adm0_idx = None
    filtered_adm0 = []
    filtered_mu = []
    mu_feats = []
    mu_idx = None

    if self.landmask_indices is not None:
      return self.landmask_indices

    adm0_feats = self.fetcher.A_fetchBaseLayer("ne_admin0").get("features", [])
    mu_feats = self.fetcher.A_fetchBaseLayer("ne_map_units").get("features", [])

    for i in range(len(adm0_feats)):
      local_p = adm0_feats[i].get("properties") or {}
      if str(local_p.get("ADM0_A3") or "").upper() != "ATA" and str(local_p.get("ISO_A3") or "").upper() != "ATA":
        filtered_adm0.append(adm0_feats[i])

    for i in range(len(mu_feats)):
      local_p = mu_feats[i].get("properties") or {}
      if str(local_p.get("ADM0_A3") or "").upper() != "ATA" and str(local_p.get("GU_A3") or "").upper() != "ATA":
        filtered_mu.append(mu_feats[i])

    adm0_idx = self.rasteriser.A_rasteriseGeometry(filtered_adm0, {"ensure_min_pixel": False})
    mu_idx = self.rasteriser.A_rasteriseGeometry(filtered_mu, {"ensure_min_pixel": False})
    self.landmask_indices = np.unique(np.concatenate([adm0_idx, mu_idx]))

    #Return statement
    return self.landmask_indices


  def isSubadminEntity (self, arg1_entity_id):
    """
    @brief Check whether an entity in country_rules.json5 belongs in subadmin_masks.json rather than country_masks.json.
    @param arg1_entity_id Canonical entity ID.
    @return Boolean True if entity is a constituent, sub-imperial or sub-national territory.
    """
    #Convert from parameters
    entity_id = str(arg1_entity_id or "").strip()

    #Return statement
    return entity_id in self.subadmin_entities_set


  def matchAdmin0Features (self, arg1_layer_key, arg2_source_obj):
    """
    @brief Match features in ne_admin0, ne_map_units or ne_subunits using ISO_A3, ADM0_A3, GU_A3 or SU_A3 codes.
    @param arg1_layer_key Base layer key ('ne_admin0', 'ne_map_units' or 'ne_subunits').
    @param arg2_source_obj Country source specification dictionary.
    @return List of matching GeoJSON Feature dictionaries.
    """
    #Convert from parameters
    layer_key = str(arg1_layer_key or "ne_admin0")
    source_obj = arg2_source_obj if isinstance(arg2_source_obj, dict) else {}

    #Declare local instance variables
    adm0_code = str(source_obj.get("adm0_a3") or "").upper()
    adm0_list_set = set(str(x).upper() for x in source_obj.get("adm0_a3_list", []) if x)
    fc_obj = self.fetcher.A_fetchBaseLayer(layer_key)
    feats = fc_obj.get("features", [])
    gu_code = str(source_obj.get("gu_a3") or "").upper()
    iso3_code = str(source_obj.get("iso3") or "").upper()
    matched_array = []
    su_code = str(source_obj.get("su_a3") or "").upper()
    su_list_set = set(str(x).upper() for x in source_obj.get("su_a3_list", []) if x)

    for i in range(len(feats)):
      local_f = feats[i]
      local_p = local_f.get("properties") or {}
      p_iso = str(local_p.get("ISO_A3") or local_p.get("ISO_A3_EH") or "").upper()
      p_adm = str(local_p.get("ADM0_A3") or "").upper()
      p_gu = str(local_p.get("GU_A3") or "").upper()
      p_su = str(local_p.get("SU_A3") or "").upper()

      if p_adm == "ATA" or p_iso == "ATA" or p_gu == "ATA":
        continue

      if su_list_set and p_su in su_list_set:
        matched_array.append(local_f)
      elif adm0_list_set and (p_adm in adm0_list_set or p_gu in adm0_list_set or p_iso in adm0_list_set):
        matched_array.append(local_f)
      elif su_code and p_su == su_code:
        matched_array.append(local_f)
      elif gu_code and (p_gu == gu_code or p_adm == gu_code):
        matched_array.append(local_f)
      elif adm0_code and (p_adm == adm0_code or p_gu == adm0_code or p_iso == adm0_code):
        matched_array.append(local_f)
      elif iso3_code and (p_iso == iso3_code or p_adm == iso3_code or p_gu == iso3_code):
        matched_array.append(local_f)

    if not matched_array and layer_key == "ne_admin0":
      target_code = adm0_code or iso3_code or gu_code
      if target_code and target_code != "ATA":
        mu_fc = self.fetcher.A_fetchBaseLayer("ne_map_units")
        mu_feats = mu_fc.get("features", [])
        for i in range(len(mu_feats)):
          local_f = mu_feats[i]
          local_p = local_f.get("properties") or {}
          if (
            str(local_p.get("GU_A3") or "").upper() == target_code
            or str(local_p.get("ADM0_A3") or "").upper() == target_code
            or str(local_p.get("ISO_A3") or "").upper() == target_code
          ):
            matched_array.append(local_f)

    #Return statement
    return matched_array


  def matchAdmin1Features (self, arg1_source_obj):
    """
    @brief Match state, province or region features in ne_admin1 for sub-national territories and historical border adjustments.
    @param arg1_source_obj Source specification dictionary with adm0_a3 and name/names/regions.
    @return List of matching GeoJSON Feature dictionaries.
    """
    #Convert from parameters
    source_obj = arg1_source_obj if isinstance(arg1_source_obj, dict) else {}

    #Declare local instance variables
    adm0_code = str(source_obj.get("adm0_a3") or "").upper()
    fc_obj = self.fetcher.A_fetchBaseLayer("ne_admin1")
    feats = fc_obj.get("features", [])
    matched_array = []
    raw_names = []
    reg_slugs = set()
    target_slugs = set()

    if "name" in source_obj and source_obj["name"]:
      raw_names.append(str(source_obj["name"]))
    if isinstance(source_obj.get("names"), list):
      for i in range(len(source_obj["names"])):
        raw_names.append(str(source_obj["names"][i]))
    if isinstance(source_obj.get("regions"), list):
      for i in range(len(source_obj["regions"])):
        local_rs = self.fetcher.normaliseAsciiSlug(str(source_obj["regions"][i])).replace("_", "")
        if local_rs:
          reg_slugs.add(local_rs)

    for i in range(len(raw_names)):
      local_s = self.fetcher.normaliseAsciiSlug(raw_names[i]).replace("_", "")
      if local_s:
        target_slugs.add(local_s)

    for i in range(len(feats)):
      local_f = feats[i]
      local_p = local_f.get("properties") or {}
      p_adm = str(local_p.get("adm0_a3") or "").upper()
      p_sov = str(local_p.get("sov_a3") or "").upper()
      if adm0_code and p_adm != adm0_code and p_sov != adm0_code:
        continue
      if reg_slugs:
        p_reg = self.fetcher.normaliseAsciiSlug(str(local_p.get("region") or "")).replace("_", "")
        if p_reg and p_reg in reg_slugs:
          matched_array.append(local_f)
          continue
      cand_fields = [
        str(local_p.get("name") or ""),
        str(local_p.get("name_en") or ""),
        str(local_p.get("gn_name") or ""),
        str(local_p.get("woe_name") or ""),
        str(local_p.get("name_local") or "")
      ]
      alt_str = str(local_p.get("name_alt") or "")
      if alt_str:
        cand_fields.extend(alt_str.split("|"))
      for x in range(len(cand_fields)):
        local_cs = self.fetcher.normaliseAsciiSlug(cand_fields[x]).replace("_", "")
        if local_cs and local_cs in target_slugs:
          matched_array.append(local_f)
          break

    #Return statement
    return matched_array


  def matchBritishIndiaFeatures (self, arg1_source_obj):
    """
    @brief Match features from the 1948 British India shapefile layer by NAME_2, PART_OF or TYPE_1.
    @param arg1_source_obj Source dictionary with names_2, part_of or all_features.
    @return List of matching GeoJSON Feature dictionaries.
    """
    #Convert from parameters
    source_obj = arg1_source_obj if isinstance(arg1_source_obj, dict) else {}

    #Declare local instance variables
    fc_obj = self.fetcher.A_fetchBaseLayer("british_india_1948")
    feats = fc_obj.get("features", [])
    matched_array = []
    names_2_slugs = set()
    part_slugs = set()

    if source_obj.get("all_features"):
      return feats

    for i in range(len(source_obj.get("names_2", []))):
      names_2_slugs.add(self.fetcher.normaliseAsciiSlug(source_obj["names_2"][i]).replace("_", ""))
    for i in range(len(source_obj.get("part_of", []))):
      part_slugs.add(self.fetcher.normaliseAsciiSlug(source_obj["part_of"][i]).replace("_", ""))

    for i in range(len(feats)):
      local_f = feats[i]
      local_p = local_f.get("properties") or {}
      n2_slug = self.fetcher.normaliseAsciiSlug(str(local_p.get("NAME_2") or "")).replace("_", "")
      po_slug = self.fetcher.normaliseAsciiSlug(str(local_p.get("PART_OF") or "")).replace("_", "")
      if (n2_slug and n2_slug in names_2_slugs) or (po_slug and po_slug in part_slugs):
        matched_array.append(local_f)

    #Return statement
    return matched_array


  def matchGadmSubset (self, arg1_iso3, arg2_level, arg3_names_list, arg4_names_1_list=None, arg5_names_2_list=None):
    """
    @brief Match features in a UC Davis GADM 4.1 country/level layer by compact ASCII name slug with optional parent filters.
    @param arg1_iso3 Three-letter ISO3 code.
    @param arg2_level Integer administrative level (0, 1, 2 or 3).
    @param arg3_names_list List of target feature names at arg2_level.
    @param arg4_names_1_list Optional list of parent NAME_1 filters.
    @param arg5_names_2_list Optional list of parent NAME_2 filters.
    @return List of matching GeoJSON Feature dictionaries.
    """
    #Convert from parameters
    iso3 = str(arg1_iso3 or "").strip().upper()
    level = int(arg2_level)
    names_list = arg3_names_list if isinstance(arg3_names_list, list) else []
    names_1_list = arg4_names_1_list if isinstance(arg4_names_1_list, list) else []
    names_2_list = arg5_names_2_list if isinstance(arg5_names_2_list, list) else []

    #Declare local instance variables
    fc_obj = self.fetcher.B_fetchGadmLayer(iso3, level)
    feats = fc_obj.get("features", [])
    matched_array = []
    n1_slugs = set(self.fetcher.normaliseAsciiSlug(n).replace("_", "") for n in names_1_list if n)
    n2_slugs = set(self.fetcher.normaliseAsciiSlug(n).replace("_", "") for n in names_2_list if n)
    name_field = f"NAME_{level}"
    target_slugs = set(self.fetcher.normaliseAsciiSlug(n).replace("_", "") for n in names_list if n)
    var_field = f"VARNAME_{level}"

    if level == 0:
      return feats

    for i in range(len(feats)):
      local_f = feats[i]
      local_p = local_f.get("properties") or {}
      if n1_slugs:
        p1_slug = self.fetcher.normaliseAsciiSlug(str(local_p.get("NAME_1") or "")).replace("_", "")
        if p1_slug not in n1_slugs:
          continue
      if n2_slugs:
        p2_slug = self.fetcher.normaliseAsciiSlug(str(local_p.get("NAME_2") or "")).replace("_", "")
        if p2_slug not in n2_slugs:
          continue
      if not target_slugs:
        matched_array.append(local_f)
        continue
      cands = [str(local_p.get(name_field) or "")]
      var_txt = str(local_p.get(var_field) or "")
      if var_txt:
        cands.extend(var_txt.split("|"))
      for x in range(len(cands)):
        cs = self.fetcher.normaliseAsciiSlug(cands[x]).replace("_", "")
        if cs and cs in target_slugs:
          matched_array.append(local_f)
          break

    #Return statement
    return matched_array


  def matchHistoricalBasemapFeatures (self, arg1_layer_key, arg2_source_obj):
    """
    @brief Match features from generic configured GeoJSON base layers.
    @param arg1_layer_key Layer key in areal_mask_config.json5.
    @param arg2_source_obj Source specification dictionary.
    @return List of matching GeoJSON Feature dictionaries.
    """
    #Convert from parameters
    layer_key = str(arg1_layer_key or "")
    source_obj = arg2_source_obj if isinstance(arg2_source_obj, dict) else {}

    #Declare local instance variables
    fc_obj = self.fetcher.A_fetchBaseLayer(layer_key)
    feats = fc_obj.get("features", [])
    matched_array = []
    target_slug = self.fetcher.normaliseAsciiSlug(str(source_obj.get("name") or "")).replace("_", "")

    if source_obj.get("all_features"):
      return feats

    for i in range(len(feats)):
      local_f = feats[i]
      local_p = local_f.get("properties") or {}
      for _, local_v in local_p.items():
        if isinstance(local_v, str):
          v_slug = self.fetcher.normaliseAsciiSlug(local_v).replace("_", "")
          if v_slug and v_slug == target_slug:
            matched_array.append(local_f)
            break

    #Return statement
    return matched_array


  def matchPhersuFeatures (self, arg1_source_obj):
    """
    @brief Match historical sovereign polity polygons in a Phersu snapshot GeoJSON by normalised state label.
    @param arg1_source_obj Source dictionary containing 'snapshot' and 'state' or 'states'.
    @return List of matching GeoJSON Feature dictionaries.
    """
    #Convert from parameters
    source_obj = arg1_source_obj if isinstance(arg1_source_obj, dict) else {}

    #Declare local instance variables
    fc_obj = {}
    feats = []
    matched_array = []
    raw_states = []
    snapshot_name = str(source_obj.get("snapshot") or "").strip()
    target_slugs = set()

    if not snapshot_name:
      sys.stderr.write("Console error: Phersu source missing snapshot filename.\n")
      return matched_array

    if source_obj.get("state"):
      raw_states.append(str(source_obj["state"]))
    if isinstance(source_obj.get("states"), list):
      for i in range(len(source_obj["states"])):
        raw_states.append(str(source_obj["states"][i]))

    for i in range(len(raw_states)):
      local_s = self.fetcher.normaliseAsciiSlug(raw_states[i]).replace("_", "")
      if local_s:
        target_slugs.add(local_s)

    fc_obj = self.fetcher.C_fetchPhersuSnapshot(snapshot_name)
    feats = fc_obj.get("features", [])
    for i in range(len(feats)):
      local_f = feats[i]
      local_p = local_f.get("properties") or {}
      st_clean = str(local_p.get("state_clean") or local_p.get("state") or "")
      st_slug = self.fetcher.normaliseAsciiSlug(st_clean).replace("_", "")
      if st_slug and st_slug in target_slugs:
        matched_array.append(local_f)

    #Return statement
    return matched_array


  def matchRussia1897Features (self, arg1_source_obj):
    """
    @brief Match 1897 Russian Empire governorates / oblasts by source_english property or all_features flag.
    @param arg1_source_obj Source dictionary with source_english list or all_features boolean.
    @return List of matching GeoJSON Feature dictionaries.
    """
    #Convert from parameters
    source_obj = arg1_source_obj if isinstance(arg1_source_obj, dict) else {}

    #Declare local instance variables
    fc_obj = self.fetcher.A_fetchBaseLayer("russia_1897")
    feats = fc_obj.get("features", [])
    matched_array = []
    names_list = source_obj.get("source_english", [])
    target_slugs = set(self.fetcher.normaliseAsciiSlug(n).replace("_", "") for n in names_list if n)

    if source_obj.get("all_features"):
      return feats

    for i in range(len(feats)):
      local_f = feats[i]
      local_p = local_f.get("properties") or {}
      se_slug = self.fetcher.normaliseAsciiSlug(str(local_p.get("source_english") or "")).replace("_", "")
      if se_slug and se_slug in target_slugs:
        matched_array.append(local_f)

    #Return statement
    return matched_array


  def resolveSingleCountry (self, arg1_country_id, arg2_visiting_set=None):
    """
    @brief Resolve and rasterise a single canonical country entity (supporting union, difference, polygon, bbox, Phersu, GADM and NE layers).
    @param arg1_country_id Canonical country ID key in country_rules.json5.
    @param arg2_visiting_set Set of currently visiting country IDs to guard against cycles.
    @return Resolved country entity dictionary.
    """
    #Convert from parameters
    country_id = str(arg1_country_id or "").strip()
    visiting_set = arg2_visiting_set if isinstance(arg2_visiting_set, set) else set()

    #Declare local instance variables
    cfg = {}
    empty_idx = np.zeros(0, dtype=np.int32)
    fallback_pt = None
    flat_idx = None
    layer_key = ""
    matched_feats = []
    metrics_obj = {}
    poly_coords = []
    record_obj = {}
    source_obj = {}
    source_type = ""

    if country_id in self.resolved_countries_obj:
      return self.resolved_countries_obj[country_id]

    if country_id not in self.countries_cfg or country_id in visiting_set:
      sys.stderr.write(f"Console error: invalid or cyclic country definition: {country_id}\n")
      return {"entity_id": country_id, "flat_indices": empty_idx, "metrics": self.rasteriser.computeMaskMetrics(empty_idx)}

    visiting_set.add(country_id)
    cfg = self.countries_cfg[country_id]
    source_obj = cfg.get("source", {})
    source_type = str(source_obj.get("type") or "layer")
    layer_key = str(source_obj.get("layer") or "")
    fallback_pt = source_obj.get("lonlat_fallback")

    if source_type == "union":
      member_arrays = []
      members = source_obj.get("members", [])
      for i in range(len(members)):
        local_mem = self.resolveSingleCountry(str(members[i]), visiting_set)
        if local_mem["flat_indices"].size > 0:
          member_arrays.append(local_mem["flat_indices"])
      flat_idx = np.unique(np.concatenate(member_arrays)) if member_arrays else empty_idx
      flat_idx = self.applySourceModifiers(flat_idx, source_obj, visiting_set)
    elif source_type == "difference":
      base_rec = self.resolveSingleCountry(str(source_obj.get("base") or ""), visiting_set)
      flat_idx = base_rec["flat_indices"].copy()
      sub_list = source_obj.get("subtract", [])
      for i in range(len(sub_list)):
        local_sub = self.resolveSingleCountry(str(sub_list[i]), visiting_set)
        if local_sub["flat_indices"].size > 0 and flat_idx.size > 0:
          flat_idx = np.setdiff1d(flat_idx, local_sub["flat_indices"], assume_unique=True)
      flat_idx = self.applySourceModifiers(flat_idx, source_obj, visiting_set)
    elif source_type == "polygon":
      poly_coords = source_obj.get("coords", [])
      flat_idx = self.rasteriser.A_rasteriseGeometry({"coordinates": [poly_coords], "type": "Polygon"}, {"fallback_lonlat": fallback_pt})
      flat_idx = self.applySourceModifiers(flat_idx, source_obj, visiting_set)
    elif source_type == "bbox":
      bb = source_obj.get("bbox", [0.0, 0.0, 0.1, 0.1])
      flat_idx = self.rasteriser.rasteriseBbox(bb[0], bb[1], bb[2], bb[3])
      flat_idx = self.applySourceModifiers(flat_idx, source_obj, visiting_set)
    else:
      if layer_key in ("ne_admin0", "ne_map_units", "ne_subunits"):
        matched_feats = self.matchAdmin0Features(layer_key, source_obj)
      elif layer_key == "ne_admin1":
        matched_feats = self.matchAdmin1Features(source_obj)
      elif layer_key == "british_india_1948":
        matched_feats = self.matchBritishIndiaFeatures(source_obj)
      elif layer_key == "russia_1897":
        matched_feats = self.matchRussia1897Features(source_obj)
      elif layer_key == "phersu":
        matched_feats = self.matchPhersuFeatures(source_obj)
      elif layer_key == "gadm":
        matched_feats = self.matchGadmSubset(
          str(source_obj.get("gadm_iso3") or ""),
          int(source_obj.get("gadm_level") or 1),
          source_obj.get("names", []),
          source_obj.get("names_1", []),
          source_obj.get("names_2", [])
        )
      else:
        matched_feats = self.matchHistoricalBasemapFeatures(layer_key, source_obj)

      flat_idx = self.rasteriser.A_rasteriseGeometry(matched_feats, {"fallback_lonlat": fallback_pt})
      flat_idx = self.applySourceModifiers(flat_idx, source_obj, visiting_set)

    visiting_set.discard(country_id)

    if flat_idx is None or flat_idx.size == 0:
      sys.stderr.write(f"Console error: country '{country_id}' rasterised to 0 pixels!\n")
      flat_idx = empty_idx

    metrics_obj = self.rasteriser.computeMaskMetrics(flat_idx)
    record_obj = {
      "category": "country",
      "entity_id": country_id,
      "era_type": str(cfg.get("era_type", "modern")),
      "flat_indices": flat_idx,
      "metrics": metrics_obj,
      "name": str(cfg.get("name", country_id)),
      "source_summary": source_obj,
      "temporal_eras": cfg.get("temporal_eras", []),
      "valid_years": cfg.get("valid_years", [1495, 2025])
    }
    self.resolved_countries_obj[country_id] = record_obj

    #Return statement
    return record_obj
