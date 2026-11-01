"""@brief Resolves canonical urban locality [lng, lat] WGS84 coordinates via verified rules, Wikipedia GeoHack, Photon OSM and Nominatim."""

import sys


class CityMaskResolver:
  """@brief Geocodes all Global Collaboratory urban localities and historical reference cities to WGS84 [lng, lat] coordinates."""

  def __init__ (self, arg1_fetcher, arg2_city_rules_obj):
    """
    @brief Initialise CityMaskResolver with GeoJsonFetcher and parsed city_rules.json5.
    @param arg1_fetcher GeoJsonFetcher instance.
    @param arg2_city_rules_obj Parsed city_rules.json5 dictionary.
    """
    #Convert from parameters
    fetcher = arg1_fetcher
    city_rules_obj = arg2_city_rules_obj if isinstance(arg2_city_rules_obj, dict) else {}

    #Declare local instance variables
    self.cities_cfg = city_rules_obj.get("cities", {})
    self.city_aliases_cfg = city_rules_obj.get("city_aliases", {})
    self.country_suffixes_cfg = city_rules_obj.get("country_suffixes", {})
    self.fetcher = fetcher
    self.resolved_cities_obj = {}
    self.sorted_suffixes = sorted(self.country_suffixes_cfg.keys(), key=lambda local_s: len(local_s), reverse=True)
    self.western_iso2_set = {
      "AR", "BO", "BR", "CA", "CL", "CO", "CR", "CU", "DO", "EC", "GT", "HN", "HT",
      "JM", "MX", "NI", "PA", "PE", "PR", "PY", "SV", "TT", "US", "UY", "VE"
    }


  def A_resolveAllCities (self, arg1_extra_city_keys_array=None):
    """
    @brief Step A: Resolve all configured cities in city_rules.json5 plus any extra corpus city keys into [lng, lat] coordinates.
    @param arg1_extra_city_keys_array Optional list of additional raw or canonical city keys.
    @return Dictionary mapping canonical city_id -> [lng, lat] float coordinate pair.
    """
    #Convert from parameters
    extra_city_keys_array = arg1_extra_city_keys_array if isinstance(arg1_extra_city_keys_array, list) else []

    #Declare local instance variables
    all_raw_keys = list(self.cities_cfg.keys()) + extra_city_keys_array
    photon_results_map = {}
    plans_map = {}
    unique_keys = sorted(set(self.normaliseCityKey(k) for k in all_raw_keys if str(k).strip()))
    wiki_results_map = {}
    wiki_titles = []

    for i in range(len(unique_keys)):
      local_cid = unique_keys[i]
      local_cfg = self.cities_cfg.get(local_cid, {})
      explicit_coords = local_cfg.get("coords")
      if isinstance(explicit_coords, list) and len(explicit_coords) >= 2:
        self.resolved_cities_obj[local_cid] = [
          round(float(explicit_coords[0]), 5),
          round(float(explicit_coords[1]), 5)
        ]
        continue

      local_plan = self.buildCityQueryPlan(local_cid)
      plans_map[local_cid] = local_plan
      if local_plan["wiki"] and local_plan["wiki"] not in wiki_titles:
        wiki_titles.append(local_plan["wiki"])
      if local_plan["wiki_fallback"] and local_plan["wiki_fallback"] not in wiki_titles:
        wiki_titles.append(local_plan["wiki_fallback"])

    if wiki_titles:
      wiki_results_map = self.fetcher.D_fetchWikipediaCoordinatesBatch(wiki_titles)
    if plans_map:
      photon_results_map = self.fetchPhotonForMissing(plans_map, wiki_results_map)

    for local_cid in sorted(plans_map.keys()):
      local_plan = plans_map[local_cid]
      local_coord = self.selectBestCoordinates(local_cid, local_plan, wiki_results_map, photon_results_map.get(local_cid))
      self.resolved_cities_obj[local_cid] = [
        round(float(local_coord["lon"]), 5),
        round(float(local_coord["lat"]), 5)
      ]

    #Return statement
    return self.resolved_cities_obj


  def buildCityQueryPlan (self, arg1_city_id):
    """
    @brief Construct Wikipedia GeoHack title and Photon OpenStreetMap query parameters for a city key.
    @param arg1_city_id Canonical city key (e.g. 'venice', 'tokyo', 'salvador_brazil', 'allentown_usa').
    @return Dictionary containing name, query, wiki, wiki_fallback and iso2.
    """
    #Convert from parameters
    city_id = str(arg1_city_id or "").strip()

    #Declare local instance variables
    base_slug = city_id
    base_title = ""
    country_name = ""
    display_name = ""
    iso2_code = ""
    query_str = ""
    rule_obj = {}
    wiki_fallback = ""
    wiki_title = ""

    if city_id in self.cities_cfg:
      rule_obj = self.cities_cfg[city_id]
      display_name = str(rule_obj.get("name") or city_id.replace("_", " ").title())
      wiki_title = str(rule_obj.get("wiki") or display_name)
      query_str = str(rule_obj.get("query") or display_name)
      iso2_code = str(rule_obj.get("iso2") or "").upper()
      wiki_fallback = str(rule_obj.get("wiki_fallback") or "")
      return {
        "iso2": iso2_code,
        "name": display_name,
        "query": query_str,
        "wiki": wiki_title,
        "wiki_fallback": wiki_fallback
      }

    for i in range(len(self.sorted_suffixes)):
      local_sfx = self.sorted_suffixes[i]
      if city_id.endswith(f"_{local_sfx}") and len(city_id) > len(local_sfx) + 1:
        base_slug = city_id[:-(len(local_sfx) + 1)]
        sfx_meta = self.country_suffixes_cfg[local_sfx]
        country_name = str(sfx_meta.get("country") or "")
        iso2_code = str(sfx_meta.get("iso2") or "").upper()
        break

    base_title = base_slug.replace("_", " ").title()
    base_title = base_title.replace(" De ", " de ").replace(" Del ", " del ").replace(" Do ", " do ")
    if country_name:
      display_name = f"{base_title}, {country_name}"
      query_str = f"{base_title}, {country_name}"
      wiki_title = f"{base_title}, {country_name}" if iso2_code in ("US", "CA") else base_title
      wiki_fallback = base_title if wiki_title != base_title else f"{base_title}, {country_name}"
    else:
      display_name = base_title
      query_str = base_title
      wiki_title = base_title
      wiki_fallback = ""

    #Return statement
    return {
      "iso2": iso2_code,
      "name": display_name,
      "query": query_str,
      "wiki": wiki_title,
      "wiki_fallback": wiki_fallback
    }


  def fetchPhotonForMissing (self, arg1_plans_map, arg2_wiki_map):
    """
    @brief Query Photon OpenStreetMap API for cities unresolved by Wikipedia GeoHack.
    @param arg1_plans_map Dictionary mapping city_id -> query plan dictionary.
    @param arg2_wiki_map Batch Wikipedia GeoHack coordinate dictionary.
    @return Dictionary mapping city_id -> Photon hit dictionary (or None).
    """
    #Convert from parameters
    plans_map = arg1_plans_map if isinstance(arg1_plans_map, dict) else {}
    wiki_map = arg2_wiki_map if isinstance(arg2_wiki_map, dict) else {}

    #Declare local instance variables
    city_ids = sorted(plans_map.keys())
    results_map = {}

    for i in range(len(city_ids)):
      local_cid = city_ids[i]
      local_plan = plans_map[local_cid]
      w_hit = wiki_map.get(local_plan.get("wiki", "")) or wiki_map.get(local_plan.get("wiki_fallback", ""))
      if w_hit is not None and local_plan.get("iso2") in self.western_iso2_set and float(w_hit["lon"]) > -30.0:
        w_hit = None
      if w_hit is None:
        results_map[local_cid] = self.fetcher.E_fetchPhotonCity(
          local_plan["query"],
          {"expected_iso2": local_plan["iso2"] or None}
        )

    #Return statement
    return results_map


  def normaliseCityKey (self, arg1_raw_city_key):
    """
    @brief Map a raw corpus locality label or slug to its clean canonical key in city_masks.json.
    @param arg1_raw_city_key Raw corpus locality string (e.g. 'City of Salvador', 'Tokyo (Edo)', 'Charleston, SC').
    @return Canonical snake_case city identifier.
    """
    #Convert from parameters
    raw_city_key = str(arg1_raw_city_key or "").strip()

    #Declare local instance variables
    slug = self.fetcher.normaliseAsciiSlug(raw_city_key)

    if slug in self.city_aliases_cfg:
      return str(self.city_aliases_cfg[slug])
    if raw_city_key.lower() in self.city_aliases_cfg:
      return str(self.city_aliases_cfg[raw_city_key.lower()])

    #Return statement
    return slug


  def selectBestCoordinates (self, arg1_city_id, arg2_plan_obj, arg3_wiki_map, arg4_photon_hit):
    """
    @brief Cross-validate Wikipedia GeoHack and Photon OSM coordinates for a city, falling back to Nominatim point lookup if needed.
    @param arg1_city_id Canonical city identifier.
    @param arg2_plan_obj City query plan dictionary.
    @param arg3_wiki_map Batch Wikipedia GeoHack coordinate dictionary.
    @param arg4_photon_hit Photon OSM result dictionary or None.
    @return Dictionary containing lon and lat floats.
    """
    #Convert from parameters
    city_id = str(arg1_city_id or "")
    plan_obj = arg2_plan_obj if isinstance(arg2_plan_obj, dict) else {}
    wiki_map = arg3_wiki_map if isinstance(arg3_wiki_map, dict) else {}
    photon_hit = arg4_photon_hit if isinstance(arg4_photon_hit, dict) else None

    #Declare local instance variables
    nom_pt = None
    w_hit = wiki_map.get(plan_obj.get("wiki", "")) or wiki_map.get(plan_obj.get("wiki_fallback", ""))

    if w_hit is not None and plan_obj.get("iso2") in self.western_iso2_set and float(w_hit["lon"]) > -30.0:
      w_hit = None

    if w_hit is not None and photon_hit is not None:
      dlon = abs(float(w_hit["lon"]) - float(photon_hit["lon"]))
      dlat = abs(float(w_hit["lat"]) - float(photon_hit["lat"]))
      if dlon <= 1.5 and dlat <= 1.5:
        return {"lat": float(w_hit["lat"]), "lon": float(w_hit["lon"])}
      if plan_obj.get("iso2") and str(photon_hit.get("countrycode") or "").upper() == plan_obj["iso2"]:
        if plan_obj["iso2"] in ("US", "CA", "BR", "MX", "AR", "CO", "VE", "PE", "CL") and city_id not in self.cities_cfg:
          return {"lat": float(photon_hit["lat"]), "lon": float(photon_hit["lon"])}
      return {"lat": float(w_hit["lat"]), "lon": float(w_hit["lon"])}

    if w_hit is not None:
      return {"lat": float(w_hit["lat"]), "lon": float(w_hit["lon"])}

    if photon_hit is not None:
      return {"lat": float(photon_hit["lat"]), "lon": float(photon_hit["lon"])}

    nom_pt = self.fetcher.F_fetchNominatimCityPoint(plan_obj.get("query", city_id))
    if nom_pt is not None:
      return {"lat": float(nom_pt["lat"]), "lon": float(nom_pt["lon"])}

    sys.stderr.write(f"Console error: failed geocoding city '{city_id}' ({plan_obj.get('query')})\n")

    #Return statement
    return {"lat": 0.0, "lon": 0.0}
