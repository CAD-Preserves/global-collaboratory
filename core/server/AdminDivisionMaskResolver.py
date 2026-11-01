"""@brief Resolves historical and modern subadministrative divisions (1495-2025) across all Global Collaboratory regional datasets."""

import sys
import numpy as np


class AdminDivisionMaskResolver:
  """@brief Resolves sub-national states, provinces, presidencies, princely agencies, collectorates, concelhos, residencies, uezds, guberniyas and captaincies."""

  def __init__ (self, arg1_fetcher, arg2_rasteriser, arg3_country_resolver, arg4_city_resolver, arg5_admin_rules_obj):
    """
    @brief Initialise AdminDivisionMaskResolver with fetcher, rasteriser, CountryMaskResolver, CityMaskResolver and admin_division_rules.json5.
    @param arg1_fetcher GeoJsonFetcher instance.
    @param arg2_rasteriser EquirectangularRasteriser instance.
    @param arg3_country_resolver CountryMaskResolver instance (with canonical countries already resolved).
    @param arg4_city_resolver CityMaskResolver instance.
    @param arg5_admin_rules_obj Parsed admin_division_rules.json5 dictionary.
    """
    #Convert from parameters
    fetcher = arg1_fetcher
    rasteriser = arg2_rasteriser
    country_resolver = arg3_country_resolver
    city_resolver = arg4_city_resolver
    admin_rules_obj = arg5_admin_rules_obj if isinstance(arg5_admin_rules_obj, dict) else {}

    #Declare local instance variables
    self.city_resolver = city_resolver
    self.country_resolver = country_resolver
    self.divisions_cfg = admin_rules_obj.get("divisions", {})
    self.fetcher = fetcher
    self.groups_cfg = admin_rules_obj.get("groups", {})
    self.partition_sets_cfg = admin_rules_obj.get("partition_sets", [])
    self.rasteriser = rasteriser
    self.resolved_divisions_obj = {}
    self.resolved_groups_obj = {}


  def A_resolveAllAdminDivisions (self):
    """
    @brief Step A: Resolve all configured subadministrative divisions, snap partition sets and recompute composite unions.
    @return Dictionary containing 'divisions' and 'groups' resolved entity maps.
    """
    #Declare local instance variables
    all_div_keys = sorted(self.divisions_cfg.keys())
    parent_buckets = {}

    for i in range(len(all_div_keys)):
      local_dk = all_div_keys[i]
      self.resolveDivisionByKey(local_dk, set())

    self.applyPartitionSets()
    self.recomputeCompositeDivisions()

    for local_eid, div_rec in sorted(self.resolved_divisions_obj.items()):
      c_parent = str(div_rec.get("canonical_parent") or "")
      if c_parent and div_rec["flat_indices"].size > 0:
        parent_buckets.setdefault(c_parent, []).append(div_rec["flat_indices"])

    for local_parent, idx_list in sorted(parent_buckets.items()):
      union_idx = np.unique(np.concatenate(idx_list))
      self.resolved_groups_obj[local_parent] = {
        "canonical_group": local_parent,
        "category": "admin_group",
        "entity_id": f"canonical_group:{local_parent}",
        "flat_indices": union_idx,
        "metrics": self.rasteriser.computeMaskMetrics(union_idx),
        "name": f"Subadministrative group: {local_parent}"
      }

    #Return statement
    return {
      "divisions": self.resolved_divisions_obj,
      "groups": self.resolved_groups_obj
    }


  def applyDivisionModifiers (self, arg1_flat_indices, arg2_rule_obj, arg3_group_cfg, arg4_layer_type):
    """
    @brief Apply extra GADM/admin1 unions, exclusions, 10m landmask clipping, parent country clipping and frontier snapping.
    @param arg1_flat_indices Initial sorted 1D int32 array of flat pixel indices.
    @param arg2_rule_obj Division rule dictionary.
    @param arg3_group_cfg Group metadata dictionary.
    @param arg4_layer_type Resolved primary layer type string.
    @return Modified sorted 1D int32 array of flat pixel indices.
    """
    #Convert from parameters
    flat_indices = arg1_flat_indices
    rule_obj = arg2_rule_obj if isinstance(arg2_rule_obj, dict) else {}
    group_cfg = arg3_group_cfg if isinstance(arg3_group_cfg, dict) else {}
    layer_type = str(arg4_layer_type or "")

    #Declare local instance variables
    clip_countries = []
    excl_admin1 = rule_obj.get("exclude_admin1", [])
    excl_countries = rule_obj.get("exclude_countries", [])
    excl_gadm = rule_obj.get("exclude_gadm", [])
    extra_countries = rule_obj.get("extra_countries", [])
    extra_gadm = rule_obj.get("extra_gadm", [])
    grp_clip = str(group_cfg.get("clip_to_country") or "").strip()
    non_ne_layers = {"british_india_1948", "gadm", "phersu", "russia_1897", "uk_counties", "uk_historic_counties"}
    parts_list = []
    should_snap = False

    if isinstance(extra_gadm, list) and extra_gadm:
      parts_list = [flat_indices] if flat_indices.size > 0 else []
      for i in range(len(extra_gadm)):
        local_g = extra_gadm[i]
        local_feats = self.country_resolver.matchGadmSubset(
          str(local_g.get("gadm_iso3") or ""),
          int(local_g.get("gadm_level") or 1),
          local_g.get("names", []),
          local_g.get("names_1", []),
          local_g.get("names_2", [])
        )
        local_idx = self.rasteriser.A_rasteriseGeometry(local_feats, {"ensure_min_pixel": False})
        if local_g.get("clip_to_countries"):
          local_clip = self.country_resolver.collectCountryUnionIndices(local_g["clip_to_countries"], set())
          if local_g.get("snap_to_host", False):
            local_idx = self.rasteriser.snapHistoricalFrontierToHost(local_idx, local_clip, local_g.get("snap_options"))
          else:
            local_idx = self.rasteriser.clipIndicesWithFallback(local_idx, local_clip)
        if local_idx.size > 0:
          parts_list.append(local_idx)
      flat_indices = np.unique(np.concatenate(parts_list)) if parts_list else flat_indices

    if isinstance(extra_countries, list) and extra_countries:
      parts_list = [flat_indices] if flat_indices.size > 0 else []
      ex_c_idx = self.country_resolver.collectCountryUnionIndices(extra_countries, set())
      if ex_c_idx.size > 0:
        parts_list.append(ex_c_idx)
      flat_indices = np.unique(np.concatenate(parts_list)) if parts_list else flat_indices

    if isinstance(excl_admin1, list) and excl_admin1 and flat_indices.size > 0:
      for i in range(len(excl_admin1)):
        local_ex = excl_admin1[i]
        local_feats = self.matchAdmin1ByNamesOrRegions(local_ex.get("adm0_a3", ""), local_ex.get("names", []), local_ex.get("regions", []))
        local_sub = self.rasteriser.A_rasteriseGeometry(local_feats, {"ensure_min_pixel": False})
        if local_sub.size > 0:
          reduced_a1 = np.setdiff1d(flat_indices, local_sub, assume_unique=True)
          if reduced_a1.size > 0:
            flat_indices = reduced_a1

    if isinstance(excl_gadm, list) and excl_gadm and flat_indices.size > 0:
      for i in range(len(excl_gadm)):
        local_g = excl_gadm[i]
        local_feats = self.country_resolver.matchGadmSubset(
          str(local_g.get("gadm_iso3") or ""),
          int(local_g.get("gadm_level") or 1),
          local_g.get("names", []),
          local_g.get("names_1", []),
          local_g.get("names_2", [])
        )
        local_sub = self.rasteriser.A_rasteriseGeometry(local_feats, {"ensure_min_pixel": False})
        if local_sub.size > 0:
          reduced_g = np.setdiff1d(flat_indices, local_sub, assume_unique=True)
          if reduced_g.size > 0:
            flat_indices = reduced_g

    if (layer_type in non_ne_layers or layer_type.startswith("gadm_")) and not rule_obj.get("do_not_clip_land"):
      flat_indices = self.rasteriser.clipIndicesWithFallback(flat_indices, self.country_resolver.getLandmaskIndices())

    if isinstance(rule_obj.get("clip_to_countries"), list) and rule_obj["clip_to_countries"]:
      clip_countries = rule_obj["clip_to_countries"]
    elif grp_clip and layer_type != "country_ref" and not rule_obj.get("do_not_clip_group"):
      clip_countries = [grp_clip]

    if clip_countries:
      clip_union = self.country_resolver.collectCountryUnionIndices(clip_countries, set())
      if clip_union.size > 0:
        default_snap = bool(group_cfg.get("snap_to_host", layer_type == "phersu"))
        should_snap = bool(rule_obj.get("snap_to_host", default_snap)) and not bool(rule_obj.get("do_not_snap_to_host", False))
        if should_snap:
          flat_indices = self.rasteriser.snapHistoricalFrontierToHost(flat_indices, clip_union, rule_obj.get("snap_options"))
        else:
          flat_indices = self.rasteriser.clipIndicesWithFallback(flat_indices, clip_union)

    if isinstance(excl_countries, list) and excl_countries and flat_indices.size > 0:
      excl_union = self.country_resolver.collectCountryUnionIndices(excl_countries, set())
      if excl_union.size > 0:
        reduced_c = np.setdiff1d(flat_indices, excl_union, assume_unique=True)
        if reduced_c.size > 0:
          flat_indices = reduced_c

    #Return statement
    return flat_indices


  def applyPartitionSets (self):
    """
    @brief Snap configured partition_sets in admin_division_rules.json5 onto their canonical parent country or division masks.
    """
    #Declare local instance variables
    num_sets = len(self.partition_sets_cfg) if isinstance(self.partition_sets_cfg, list) else 0

    for i in range(num_sets):
      pset = self.partition_sets_cfg[i]
      if not isinstance(pset, dict):
        continue
      target_country = str(pset.get("target_country") or "").strip()
      target_div = str(pset.get("target_division") or "").strip()
      if target_div and not target_div.startswith("admin:"):
        target_div = f"admin:{target_div}"
      target_indices = None

      if target_country:
        target_indices = self.country_resolver.resolveSingleCountry(target_country, set())["flat_indices"]
      elif target_div and target_div in self.resolved_divisions_obj:
        target_indices = self.resolved_divisions_obj[target_div]["flat_indices"]

      if target_indices is None or target_indices.size == 0:
        sys.stderr.write(f"Console error: partition set '{pset.get('name')}' has empty target mask.\n")
        continue

      excl_set = set()
      for x in range(len(pset.get("exclude_members", []))):
        raw_ex = str(pset["exclude_members"][x] or "").strip()
        if raw_ex:
          excl_set.add(raw_ex if raw_ex.startswith("admin:") else f"admin:{raw_ex}")

      explicit_members = set()
      for x in range(len(pset.get("members", []))):
        raw_m = str(pset["members"][x] or "").strip()
        if raw_m:
          explicit_members.add(raw_m if raw_m.startswith("admin:") else f"admin:{raw_m}")

      prefixes_list = [f"admin:{p}:" for p in pset.get("prefixes", []) if p]
      req_parent = str(pset.get("canonical_parent") or "").strip()

      canon_to_eids = {}
      canon_to_indices = {}
      for local_eid, div_rec in sorted(self.resolved_divisions_obj.items()):
        if local_eid in excl_set or not div_rec.get("canonical_key"):
          continue
        if div_rec.get("is_composite"):
          continue
        matched_member = (local_eid in explicit_members) or any(local_eid.startswith(pref) for pref in prefixes_list)
        if not matched_member:
          continue
        if req_parent and str(div_rec.get("canonical_parent") or "") != req_parent:
          continue
        ckey = str(div_rec["canonical_key"])
        canon_to_eids.setdefault(ckey, []).append(local_eid)
        if ckey not in canon_to_indices:
          canon_to_indices[ckey] = div_rec["flat_indices"]
        else:
          canon_to_indices[ckey] = np.unique(np.concatenate([canon_to_indices[ckey], div_rec["flat_indices"]]))

      if not canon_to_indices:
        continue

      snapped_map = self.rasteriser.snapPartitionToTargetMask(
        canon_to_indices,
        target_indices,
        {
          "disjoint": bool(pset.get("disjoint", True)),
          "fill_uncovered": bool(pset.get("fill_uncovered", True)),
          "priority_keys": pset.get("priority_keys", [])
        }
      )

      for local_ck, snapped_idx in snapped_map.items():
        local_metrics = self.rasteriser.computeMaskMetrics(snapped_idx)
        for x in range(len(canon_to_eids[local_ck])):
          member_eid = canon_to_eids[local_ck][x]
          self.resolved_divisions_obj[member_eid]["flat_indices"] = snapped_idx
          self.resolved_divisions_obj[member_eid]["metrics"] = local_metrics


  def matchAdmin1ByNamesOrRegions (self, arg1_adm0_a3, arg2_names_list, arg3_regions_list=None, arg4_fuzzy_stem=""):
    """
    @brief Match features in ne_admin1 by country code and state/province names or region names.
    @param arg1_adm0_a3 Three-letter country code (e.g. 'IND', 'IDN', 'JPN', 'USA').
    @param arg2_names_list Optional list of feature 'name' strings to match.
    @param arg3_regions_list Optional list of feature 'region' strings to match.
    @param arg4_fuzzy_stem Optional fallback stem slug when explicit names/regions lists are empty.
    @return List of matching GeoJSON Feature dictionaries.
    """
    #Convert from parameters
    adm0_a3 = str(arg1_adm0_a3 or "").strip().upper()
    names_list = arg2_names_list if isinstance(arg2_names_list, list) else []
    regions_list = arg3_regions_list if isinstance(arg3_regions_list, list) else []
    fuzzy_stem = str(arg4_fuzzy_stem or "").strip()

    #Declare local instance variables
    fc_obj = self.fetcher.A_fetchBaseLayer("ne_admin1")
    feats = fc_obj.get("features", [])
    fuzzy_compact = self.fetcher.normaliseAsciiSlug(fuzzy_stem).replace("_", "")
    matched_array = []
    name_slugs = set(self.fetcher.normaliseAsciiSlug(x).replace("_", "") for x in names_list if x)
    prefix_candidates = []
    reg_slugs = set(self.fetcher.normaliseAsciiSlug(x).replace("_", "") for x in regions_list if x)

    for i in range(len(feats)):
      local_f = feats[i]
      local_p = local_f.get("properties") or {}
      p_adm = str(local_p.get("adm0_a3") or "").upper()
      p_sov = str(local_p.get("sov_a3") or "").upper()
      if adm0_a3 and p_adm != adm0_a3 and p_sov != adm0_a3:
        continue

      p_reg_slug = self.fetcher.normaliseAsciiSlug(str(local_p.get("region") or "")).replace("_", "")
      if reg_slugs and p_reg_slug in reg_slugs:
        matched_array.append(local_f)
        continue

      cand_names = [
        str(local_p.get("name") or ""),
        str(local_p.get("name_en") or ""),
        str(local_p.get("gn_name") or ""),
        str(local_p.get("woe_name") or ""),
        str(local_p.get("name_local") or "")
      ]
      alt_txt = str(local_p.get("name_alt") or "")
      if alt_txt:
        cand_names.extend(alt_txt.split("|"))

      cand_slugs = [self.fetcher.normaliseAsciiSlug(c).replace("_", "") for c in cand_names if c]
      if name_slugs and any(cs in name_slugs for cs in cand_slugs if cs):
        matched_array.append(local_f)
      elif fuzzy_compact:
        if fuzzy_compact in cand_slugs or p_reg_slug == fuzzy_compact:
          matched_array.append(local_f)
        elif any(cs.startswith(fuzzy_compact) or fuzzy_compact.startswith(cs) for cs in cand_slugs if len(cs) >= 4):
          prefix_candidates.append(local_f)

    if not matched_array and prefix_candidates:
      matched_array = prefix_candidates

    #Return statement
    return matched_array


  def matchUkCountiesFeatures (self, arg1_counties_list, arg2_fallback_stem=""):
    """
    @brief Match UK ceremonial / 1974 counties from uk_counties, with automatic ne_admin1 GBR fallback.
    @param arg1_counties_list Explicit list of county names in uk_counties.
    @param arg2_fallback_stem Optional fallback county stem slug.
    @return List of matching GeoJSON Feature dictionaries.
    """
    #Convert from parameters
    counties_list = arg1_counties_list if isinstance(arg1_counties_list, list) else []
    fallback_stem = str(arg2_fallback_stem or "")

    #Declare local instance variables
    fc_obj = self.fetcher.A_fetchBaseLayer("uk_counties")
    feats = fc_obj.get("features", [])
    matched_array = []
    stem_slug = self.fetcher.normaliseAsciiSlug(fallback_stem).replace("_", "")
    stem_without_shire = stem_slug[:-5] if stem_slug.endswith("shire") and len(stem_slug) > 7 else stem_slug
    target_slugs = set(self.fetcher.normaliseAsciiSlug(c).replace("_", "") for c in counties_list if c)

    for i in range(len(feats)):
      local_f = feats[i]
      local_p = local_f.get("properties") or {}
      c_slug = self.fetcher.normaliseAsciiSlug(str(local_p.get("county") or "")).replace("_", "")
      if target_slugs and c_slug in target_slugs:
        matched_array.append(local_f)
      elif not target_slugs and stem_slug and c_slug in (stem_slug, stem_without_shire):
        matched_array.append(local_f)

    if not matched_array:
      search_names = counties_list if counties_list else [fallback_stem.replace("_", " ")]
      matched_array = self.matchAdmin1ByNamesOrRegions("GBR", search_names, [], fallback_stem)

    #Return statement
    return matched_array


  def matchUkHistoricCountiesFeatures (self, arg1_counties_list, arg2_fallback_stem=""):
    """
    @brief Match UK historic shires/counties from The Historic County Borders Project (uk_historic_counties).
    @param arg1_counties_list Explicit list of historic county names.
    @param arg2_fallback_stem Optional fallback county stem slug.
    @return List of matching GeoJSON Feature dictionaries.
    """
    #Convert from parameters
    counties_list = arg1_counties_list if isinstance(arg1_counties_list, list) else []
    fallback_stem = str(arg2_fallback_stem or "")

    #Declare local instance variables
    fc_obj = self.fetcher.A_fetchBaseLayer("uk_historic_counties")
    feats = fc_obj.get("features", [])
    matched_array = []
    stem_slug = self.fetcher.normaliseAsciiSlug(fallback_stem).replace("_", "")
    stem_without_shire = stem_slug[:-5] if stem_slug.endswith("shire") and len(stem_slug) > 7 else stem_slug
    target_slugs = set(self.fetcher.normaliseAsciiSlug(c).replace("_", "") for c in counties_list if c)

    for i in range(len(feats)):
      local_f = feats[i]
      local_p = local_f.get("properties") or {}
      n_slug = self.fetcher.normaliseAsciiSlug(str(local_p.get("NAME") or "")).replace("_", "")
      c_slug = self.fetcher.normaliseAsciiSlug(str(local_p.get("COUNTY") or "")).replace("_", "")
      if target_slugs and (n_slug in target_slugs or c_slug in target_slugs):
        matched_array.append(local_f)
      elif not target_slugs and stem_slug and (
        n_slug in (stem_slug, stem_without_shire)
        or c_slug in (stem_slug, stem_without_shire)
      ):
        matched_array.append(local_f)

    #Return statement
    return matched_array


  def recomputeCompositeDivisions (self):
    """
    @brief Re-evaluate all division_union and division_difference masks after partition_sets have snapped constituent children.
    """
    #Declare local instance variables
    comp_keys = []

    for local_dk, rule_obj in sorted(self.divisions_cfg.items()):
      if isinstance(rule_obj, dict) and rule_obj.get("layer") in ("division_union", "division_difference"):
        if not rule_obj.get("preserve_as_partition_target", False):
          comp_keys.append(local_dk)

    for _ in range(2):
      for i in range(len(comp_keys)):
        local_dk = comp_keys[i]
        local_eid = f"admin:{local_dk}"
        rule_obj = self.divisions_cfg[local_dk]
        prefix, clean_stem = local_dk.split(":", 1)
        group_cfg = self.groups_cfg.get(prefix, {})
        new_idx, _ = self.resolveRuleGeometryIndices(rule_obj, group_cfg, clean_stem, set())
        if local_eid in self.resolved_divisions_obj and new_idx.size > 0:
          self.resolved_divisions_obj[local_eid]["flat_indices"] = new_idx
          self.resolved_divisions_obj[local_eid]["metrics"] = self.rasteriser.computeMaskMetrics(new_idx)


  def resolveDivisionByKey (self, arg1_div_lookup_key, arg2_visiting_set=None):
    """
    @brief Resolve and cache a single division entry keyed by '<prefix>:<clean_stem>' in admin_division_rules.json5.
    @param arg1_div_lookup_key Division key '<prefix>:<clean_stem>'.
    @param arg2_visiting_set Recursion guard set of division lookup keys.
    @return Resolved administrative division entity dictionary.
    """
    #Convert from parameters
    div_lookup_key = str(arg1_div_lookup_key or "").strip()
    visiting_set = arg2_visiting_set if isinstance(arg2_visiting_set, set) else set()

    #Declare local instance variables
    canonical_group = ""
    canonical_key = ""
    canonical_parent = ""
    clean_stem = ""
    empty_idx = np.zeros(0, dtype=np.int32)
    entity_id = ""
    explicit_target = ""
    flat_idx = None
    group_cfg = {}
    is_composite = False
    layer_type = ""
    prefix = ""
    record_obj = {}
    rule_obj = {}
    src_summary = {}
    target_mask = ""

    if div_lookup_key.startswith("admin:"):
      div_lookup_key = div_lookup_key[6:]

    entity_id = f"admin:{div_lookup_key}"
    if entity_id in self.resolved_divisions_obj:
      return self.resolved_divisions_obj[entity_id]

    if ":" not in div_lookup_key or div_lookup_key not in self.divisions_cfg or div_lookup_key in visiting_set:
      sys.stderr.write(f"Console error: invalid or cyclic admin division definition: {div_lookup_key}\n")
      return {"canonical_key": "", "entity_id": entity_id, "flat_indices": empty_idx, "metrics": self.rasteriser.computeMaskMetrics(empty_idx)}

    visiting_set.add(div_lookup_key)
    prefix, clean_stem = div_lookup_key.split(":", 1)
    group_cfg = self.groups_cfg.get(prefix, {})
    canonical_group = str(group_cfg.get("canonical_group") or prefix)
    rule_obj = self.divisions_cfg[div_lookup_key]
    layer_type = str(rule_obj.get("layer") or group_cfg.get("default_layer") or "ne_admin1")
    is_composite = layer_type in ("division_union", "division_difference") and not bool(rule_obj.get("include_in_partition", False))

    explicit_target = str(rule_obj.get("target_mask") or "")
    if explicit_target:
      canonical_key = ""
      canonical_parent = ""
      target_mask = explicit_target
    else:
      canonical_key = str(rule_obj.get("canonical_key") or f"{canonical_group}.{clean_stem}")
      canonical_parent = canonical_key.split(".", 1)[0] if "." in canonical_key else canonical_group
      target_mask = f"subadmin:{canonical_key}"

    flat_idx, src_summary = self.resolveRuleGeometryIndices(rule_obj, group_cfg, clean_stem, visiting_set)
    visiting_set.discard(div_lookup_key)

    if flat_idx.size == 0:
      sys.stderr.write(f"Console error: admin division '{entity_id}' resolved to 0 pixels!\n")

    record_obj = {
      "canonical_key": canonical_key,
      "canonical_parent": canonical_parent,
      "category": "admin_division",
      "entity_id": entity_id,
      "era_type": str(rule_obj.get("era_type") or group_cfg.get("era_type") or "modern"),
      "flat_indices": flat_idx,
      "group_key": prefix,
      "is_composite": is_composite,
      "metrics": self.rasteriser.computeMaskMetrics(flat_idx),
      "name": str(rule_obj.get("name") or f"{clean_stem.replace('_', ' ').title()} ({prefix.upper()})"),
      "source_summary": src_summary,
      "target_mask": target_mask,
      "valid_years": rule_obj.get("valid_years", group_cfg.get("valid_years", [1495, 2025]))
    }
    self.resolved_divisions_obj[entity_id] = record_obj

    #Return statement
    return record_obj


  def resolveRuleGeometryIndices (self, arg1_rule_obj, arg2_group_cfg, arg3_clean_stem, arg4_visiting_set=None):
    """
    @brief Execute the configured geospatial lookup, scanline rasterisation and modifiers for a single division rule.
    @param arg1_rule_obj Division rule dictionary.
    @param arg2_group_cfg Group metadata dictionary from admin_division_rules.json5.
    @param arg3_clean_stem Clean division stem string.
    @param arg4_visiting_set Recursion guard set for composite divisions.
    @return Tuple (flat_indices_array, source_summary_dict).
    """
    #Convert from parameters
    rule_obj = arg1_rule_obj if isinstance(arg1_rule_obj, dict) else {}
    group_cfg = arg2_group_cfg if isinstance(arg2_group_cfg, dict) else {}
    clean_stem = str(arg3_clean_stem or "")
    visiting_set = arg4_visiting_set if isinstance(arg4_visiting_set, set) else set()

    #Declare local instance variables
    adm0_code = str(rule_obj.get("adm0_a3") or group_cfg.get("country") or "").upper()
    empty_idx = np.zeros(0, dtype=np.int32)
    extra_admin1 = rule_obj.get("extra_ne_admin1", [])
    fallback_pt = rule_obj.get("lonlat_fallback")
    feats = []
    flat_idx = None
    layer_type = str(rule_obj.get("layer") or group_cfg.get("default_layer") or "ne_admin1")

    if layer_type == "country_ref":
      c_ref = str(rule_obj.get("country_ref") or clean_stem)
      c_rec = self.country_resolver.resolveSingleCountry(c_ref, set())
      flat_idx = c_rec["flat_indices"].copy()
      flat_idx = self.applyDivisionModifiers(flat_idx, rule_obj, group_cfg, layer_type)
      return (flat_idx, {"country_ref": c_ref, "layer": "country_ref"})

    if layer_type == "division_union":
      member_arrays = []
      members = rule_obj.get("members", [])
      for i in range(len(members)):
        m_rec = self.resolveDivisionByKey(str(members[i]), set(visiting_set))
        if m_rec["flat_indices"].size > 0:
          member_arrays.append(m_rec["flat_indices"])
      flat_idx = np.unique(np.concatenate(member_arrays)) if member_arrays else empty_idx
      flat_idx = self.applyDivisionModifiers(flat_idx, rule_obj, group_cfg, layer_type)
      return (flat_idx, {"layer": "division_union", "member_count": len(members)})

    if layer_type == "division_difference":
      base_key = str(rule_obj.get("base") or "")
      if base_key.startswith("country:"):
        base_idx = self.country_resolver.resolveSingleCountry(base_key[8:], set())["flat_indices"].copy()
      else:
        base_idx = self.resolveDivisionByKey(base_key, set(visiting_set))["flat_indices"].copy()
      sub_list = rule_obj.get("subtract", [])
      for i in range(len(sub_list)):
        s_key = str(sub_list[i])
        if s_key.startswith("country:"):
          s_idx = self.country_resolver.resolveSingleCountry(s_key[8:], set())["flat_indices"]
        else:
          s_idx = self.resolveDivisionByKey(s_key, set(visiting_set))["flat_indices"]
        if s_idx.size > 0 and base_idx.size > 0:
          base_idx = np.setdiff1d(base_idx, s_idx, assume_unique=True)
      flat_idx = self.applyDivisionModifiers(base_idx, rule_obj, group_cfg, layer_type)
      return (flat_idx, {"layer": "division_difference"})

    if layer_type == "polygon":
      poly_coords = rule_obj.get("coords", [])
      flat_idx = self.rasteriser.A_rasteriseGeometry({"coordinates": [poly_coords], "type": "Polygon"}, {"fallback_lonlat": fallback_pt})
      flat_idx = self.applyDivisionModifiers(flat_idx, rule_obj, group_cfg, layer_type)
      return (flat_idx, {"layer": "polygon"})

    if layer_type == "ne_admin1":
      feats = self.matchAdmin1ByNamesOrRegions(
        adm0_code,
        rule_obj.get("names", []),
        [],
        "" if rule_obj.get("names") else clean_stem
      )
    elif layer_type == "ne_admin1_region":
      feats = self.matchAdmin1ByNamesOrRegions(
        adm0_code,
        rule_obj.get("names", []),
        rule_obj.get("regions", []),
        "" if rule_obj.get("regions") else clean_stem
      )
    elif layer_type == "british_india_1948":
      feats = self.country_resolver.matchBritishIndiaFeatures(rule_obj)
    elif layer_type == "russia_1897":
      feats = self.country_resolver.matchRussia1897Features(rule_obj)
    elif layer_type == "phersu":
      feats = self.country_resolver.matchPhersuFeatures(rule_obj)
    elif layer_type == "uk_counties":
      feats = self.matchUkCountiesFeatures(rule_obj.get("counties", []), clean_stem)
    elif layer_type == "uk_historic_counties":
      feats = self.matchUkHistoricCountiesFeatures(rule_obj.get("counties", []), clean_stem)
    elif layer_type == "gadm" or layer_type.startswith("gadm_"):
      if layer_type.startswith("gadm_"):
        parts = layer_type.split("_")
        g_iso = parts[1]
        g_lvl = int(parts[2])
      else:
        g_iso = str(rule_obj.get("gadm_iso3") or adm0_code)
        g_lvl = int(rule_obj.get("gadm_level") or 1)
      g_names = rule_obj.get("names", [])
      feats = self.country_resolver.matchGadmSubset(
        g_iso,
        g_lvl,
        g_names,
        rule_obj.get("names_1", []),
        rule_obj.get("names_2", [])
      )

    for i in range(len(extra_admin1)):
      ex_item = extra_admin1[i]
      feats.extend(self.matchAdmin1ByNamesOrRegions(ex_item.get("adm0_a3", ""), ex_item.get("names", []), ex_item.get("regions", [])))

    if feats or fallback_pt is not None:
      flat_idx = self.rasteriser.A_rasteriseGeometry(feats, {"fallback_lonlat": fallback_pt})
    else:
      flat_idx = empty_idx

    flat_idx = self.applyDivisionModifiers(flat_idx, rule_obj, group_cfg, layer_type)

    #Return statement
    return (flat_idx, {"adm0_a3": adm0_code, "feature_count": len(feats), "layer": layer_type})

