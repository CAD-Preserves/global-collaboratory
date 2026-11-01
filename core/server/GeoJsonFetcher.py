"""@brief Online GeoJSON, GADM 4.1 archive, ESRI Shapefile, Phersu historical snapshot, GeoHack, Photon and Nominatim fetcher."""

import json
import os
import re
import struct
import sys
import time
import unicodedata
import zipfile
import orjson
import requests


class GeoJsonFetcher:
  """@brief Downloads, caches and parses vector boundary layers, local Phersu snapshots and city geocoding APIs."""

  def __init__ (self, arg1_root_dir, arg2_config_obj):
    """
    @brief Initialise GeoJsonFetcher with repository root and areal_mask_config dictionary.
    @param arg1_root_dir Absolute repository root directory.
    @param arg2_config_obj Parsed areal_mask_config.json5 dictionary.
    """
    #Convert from parameters
    root_dir = str(arg1_root_dir or "")
    config_obj = arg2_config_obj if isinstance(arg2_config_obj, dict) else {}

    #Declare local instance variables
    paths_cfg = config_obj.get("paths", {})
    cache_rel = str(paths_cfg.get("cache_dir", os.path.join("tests", "geo_cache")))
    sources_cfg = config_obj.get("sources", {})
    self.base_layers_cfg = sources_cfg.get("base_layers", {})
    self.cache_dir = os.path.join(root_dir, cache_rel)
    self.gadm_memory_cache = {}
    self.gadm_template = str(sources_cfg.get("gadm_template", "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_£1£_£2£.json"))
    self.gadm_zip_template = str(sources_cfg.get("gadm_zip_template", "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_£1£_£2£.json.zip"))
    self.last_nominatim_ts = 0.0
    self.layer_memory_cache = {}
    self.nominatim_cache_obj = {}
    self.nominatim_cache_path = os.path.join(self.cache_dir, "nominatim_polygons_cache.json")
    self.nominatim_url = str(sources_cfg.get("nominatim_search_url", "https://nominatim.openstreetmap.org/search"))
    self.phersu_dir = str(paths_cfg.get("phersu_dir", "F:/scrapes/phersu/geojson"))
    self.phersu_memory_cache = {}
    self.photon_cache_obj = {}
    self.photon_cache_path = os.path.join(self.cache_dir, "photon_cities_cache.json")
    self.photon_url = str(sources_cfg.get("photon_api_url", "https://photon.komoot.io/api/"))
    self.root_dir = root_dir
    self.session = requests.Session()
    self.wiki_cache_obj = {}
    self.wiki_cache_path = os.path.join(self.cache_dir, "wikipedia_coords_cache.json")
    self.wiki_url = str(sources_cfg.get("wikipedia_api_url", "https://en.wikipedia.org/w/api.php"))

    os.makedirs(self.cache_dir, exist_ok=True)
    self.session.headers.update({
      "User-Agent": str(sources_cfg.get("user_agent", "GlobalCollaboratoryArealMasks/2.0"))
    })
    self.loadApiCaches()


  def A_fetchBaseLayer (self, arg1_layer_key):
    """
    @brief Step A: Fetch and parse a configured base geospatial layer (GeoJSON or zipped WGS84 ESRI Shapefile).
    @param arg1_layer_key Key under sources.base_layers in areal_mask_config.json5.
    @return Parsed GeoJSON FeatureCollection dictionary with healed UTF-8 property strings.
    """
    #Convert from parameters
    layer_key = str(arg1_layer_key or "").strip()

    #Declare local instance variables
    alias_map = {
      "ne_map_units": "ne_units.geojson"
    }
    cache_geojson_path = ""
    cache_zip_path = ""
    layer_cfg = {}
    layer_fmt = ""
    layer_url = ""
    parsed_fc = {"features": [], "type": "FeatureCollection"}

    if not layer_key or layer_key not in self.base_layers_cfg:
      sys.stderr.write(f"Console error: unknown base layer requested: {layer_key}\n")
      return parsed_fc

    if layer_key in self.layer_memory_cache:
      return self.layer_memory_cache[layer_key]

    layer_cfg = self.base_layers_cfg[layer_key]
    layer_fmt = str(layer_cfg.get("format", "geojson"))
    layer_url = str(layer_cfg.get("url", ""))
    cache_geojson_path = os.path.join(self.cache_dir, f"{layer_key}.geojson")

    if not os.path.exists(cache_geojson_path) and layer_key in alias_map:
      alt_path = os.path.join(self.cache_dir, alias_map[layer_key])
      if os.path.exists(alt_path):
        cache_geojson_path = alt_path

    if layer_fmt == "shapefile_zip":
      if os.path.exists(cache_geojson_path):
        parsed_fc = self.readGeoJsonDisk(cache_geojson_path)
      else:
        cache_zip_path = os.path.join(self.cache_dir, f"{layer_key}.zip")
        if not os.path.exists(cache_zip_path):
          self.downloadUrlToFile(layer_url, cache_zip_path)
        parsed_fc = self.parseShapefileZip(
          cache_zip_path,
          str(layer_cfg.get("archive_member_shp", "")),
          str(layer_cfg.get("archive_member_dbf", ""))
        )
        self.writeGeoJsonDisk(cache_geojson_path, parsed_fc)
    else:
      if not os.path.exists(cache_geojson_path):
        self.downloadUrlToFile(layer_url, cache_geojson_path)
      parsed_fc = self.readGeoJsonDisk(cache_geojson_path)

    self.healFeatureCollectionStrings(parsed_fc)
    self.layer_memory_cache[layer_key] = parsed_fc

    #Return statement
    return parsed_fc


  def B_fetchGadmLayer (self, arg1_iso3_code, arg2_admin_level):
    """
    @brief Step B: Fetch UC Davis GADM 4.1 GeoJSON (plain .json or .json.zip) for an ISO3 country and admin level.
    @param arg1_iso3_code Three-letter ISO country code (e.g. 'IND', 'IDN', 'RUS', 'GRC').
    @param arg2_admin_level Integer administrative level (0, 1, 2, or 3).
    @return Parsed GeoJSON FeatureCollection dictionary.
    """
    #Convert from parameters
    iso3_code = str(arg1_iso3_code or "").strip().upper()
    admin_level = int(arg2_admin_level)

    #Declare local instance variables
    cache_key = f"gadm41_{iso3_code}_{admin_level}"
    cache_path = os.path.join(self.cache_dir, f"{cache_key}.geojson")
    parsed_fc = {"features": [], "type": "FeatureCollection"}
    plain_url = ""
    zip_path = os.path.join(self.cache_dir, f"{cache_key}.json.zip")
    zip_url = ""

    if len(iso3_code) != 3 or admin_level < 0:
      sys.stderr.write(f"Console error: invalid GADM request {iso3_code} level {admin_level}\n")
      return parsed_fc

    if cache_key in self.gadm_memory_cache:
      return self.gadm_memory_cache[cache_key]

    if not os.path.exists(cache_path):
      zip_url = self.gadm_zip_template.replace("£1£", iso3_code).replace("£2£", str(admin_level))
      plain_url = self.gadm_template.replace("£1£", iso3_code).replace("£2£", str(admin_level))
      if os.path.exists(zip_path) or self.downloadUrlToFile(zip_url, zip_path, {"quiet_404": True}):
        try:
          with zipfile.ZipFile(zip_path, "r") as local_zf:
            json_members = [m for m in local_zf.namelist() if m.endswith(".json")]
            if json_members:
              raw_bytes = local_zf.read(json_members[0])
              with open(cache_path, "wb") as local_out:
                local_out.write(raw_bytes)
        except Exception as local_err:
          sys.stderr.write(f"Console error: failed extracting {zip_path}: {local_err}\n")
      if not os.path.exists(cache_path):
        self.downloadUrlToFile(plain_url, cache_path, {"quiet_404": True})

    if os.path.exists(cache_path):
      parsed_fc = self.readGeoJsonDisk(cache_path)
      self.healFeatureCollectionStrings(parsed_fc)

    self.gadm_memory_cache[cache_key] = parsed_fc

    #Return statement
    return parsed_fc


  def C_fetchPhersuSnapshot (self, arg1_snapshot_file):
    """
    @brief Step C: Load and cache a historical polity GeoJSON snapshot from the local Phersu repository.
    @param arg1_snapshot_file Snapshot filename (e.g. '1495.01.01.json', '1679.01.01.json', '1795.01.01.json').
    @return Parsed GeoJSON FeatureCollection dictionary with normalised state labels.
    """
    #Convert from parameters
    snapshot_file = str(arg1_snapshot_file or "").strip()

    #Declare local instance variables
    feats = []
    parsed_fc = {"features": [], "type": "FeatureCollection"}
    snap_path = ""

    if not snapshot_file:
      sys.stderr.write("Console error: empty Phersu snapshot filename provided.\n")
      return parsed_fc

    if not snapshot_file.endswith(".json"):
      snapshot_file = f"{snapshot_file}.json"

    if snapshot_file in self.phersu_memory_cache:
      return self.phersu_memory_cache[snapshot_file]

    snap_path = os.path.join(self.phersu_dir, snapshot_file)
    if not os.path.exists(snap_path):
      sys.stderr.write(f"Console error: Phersu snapshot file not found: {snap_path}\n")
      return parsed_fc

    parsed_fc = self.readGeoJsonDisk(snap_path)
    self.healFeatureCollectionStrings(parsed_fc)
    feats = parsed_fc.get("features", [])
    for i in range(len(feats)):
      local_p = feats[i].get("properties")
      if isinstance(local_p, dict) and "state" in local_p:
        local_p["state_clean"] = " ".join(str(local_p.get("state") or "").split())

    self.phersu_memory_cache[snapshot_file] = parsed_fc

    #Return statement
    return parsed_fc


  def D_fetchWikipediaCoordinatesBatch (self, arg1_titles_array):
    """
    @brief Step D: Batch-query Wikipedia GeoData API (GeoHack source) for article coordinates with HTTP 429 backoff.
    @param arg1_titles_array List of English Wikipedia article titles.
    @return Dictionary mapping requested title -> {'lon': float, 'lat': float, 'resolved_title': str}.
    """
    #Convert from parameters
    titles_array = arg1_titles_array if isinstance(arg1_titles_array, list) else []

    #Declare local instance variables
    batch_size = 45
    dirty_cache = False
    missing_titles = []
    results_obj = {}

    for i in range(len(titles_array)):
      local_t = str(titles_array[i] or "").strip()
      if local_t:
        if local_t in self.wiki_cache_obj:
          if self.wiki_cache_obj[local_t] is not None:
            results_obj[local_t] = self.wiki_cache_obj[local_t]
        elif local_t not in missing_titles:
          missing_titles.append(local_t)

    for i in range(0, len(missing_titles), batch_size):
      if i > 0:
        time.sleep(0.6)
      local_chunk = missing_titles[i:i + batch_size]
      for z in range(4):
        try:
          resp = self.session.get(
            self.wiki_url,
            params={
              "action": "query",
              "colimit": "max",
              "coprimary": "all",
              "coprop": "type|dim|globe|country",
              "format": "json",
              "prop": "coordinates",
              "redirects": 1,
              "titles": "|".join(local_chunk)
            },
            timeout=30
          )
          if resp.status_code == 200:
            payload = resp.json()
            query_obj = payload.get("query", {})
            norm_map = {}
            redir_map = {}
            for x in range(len(query_obj.get("normalized", []))):
              local_n = query_obj["normalized"][x]
              norm_map[local_n.get("from", "")] = local_n.get("to", "")
            for x in range(len(query_obj.get("redirects", []))):
              local_r = query_obj["redirects"][x]
              redir_map[local_r.get("from", "")] = local_r.get("to", "")
            pages_by_title = {}
            for _, local_page in query_obj.get("pages", {}).items():
              if isinstance(local_page, dict) and "title" in local_page:
                pages_by_title[local_page["title"]] = local_page

            for x in range(len(local_chunk)):
              orig_t = local_chunk[x]
              curr_t = norm_map.get(orig_t, orig_t)
              curr_t = redir_map.get(curr_t, curr_t)
              page_obj = pages_by_title.get(curr_t)
              coord_entry = None
              if page_obj and "coordinates" in page_obj and len(page_obj["coordinates"]) > 0:
                coords_arr = page_obj["coordinates"]
                chosen_c = None
                for y in range(len(coords_arr)):
                  if coords_arr[y].get("globe", "earth") == "earth" and "primary" in coords_arr[y]:
                    chosen_c = coords_arr[y]
                    break
                if chosen_c is None:
                  for y in range(len(coords_arr)):
                    if coords_arr[y].get("globe", "earth") == "earth":
                      chosen_c = coords_arr[y]
                      break
                if chosen_c is not None:
                  coord_entry = {
                    "lat": float(chosen_c["lat"]),
                    "lon": float(chosen_c["lon"]),
                    "resolved_title": curr_t
                  }
              self.wiki_cache_obj[orig_t] = coord_entry
              dirty_cache = True
              if coord_entry is not None:
                results_obj[orig_t] = coord_entry
            break
          elif resp.status_code == 429 or resp.status_code >= 500:
            retry_hdr = resp.headers.get("Retry-After")
            wait_sec = 2.0*(z + 1)
            if retry_hdr and str(retry_hdr).isdigit():
              wait_sec = max(wait_sec, float(retry_hdr))
            time.sleep(wait_sec)
          else:
            sys.stderr.write(f"Console error: Wikipedia GeoHack HTTP {resp.status_code}\n")
            break
        except Exception as local_err:
          if z == 3:
            sys.stderr.write(f"Console error: Wikipedia GeoHack batch request failed: {local_err}\n")
          time.sleep(1.5*(z + 1))

    if dirty_cache:
      self.saveJsonCache(self.wiki_cache_path, self.wiki_cache_obj)

    #Return statement
    return results_obj


  def E_fetchPhotonCity (self, arg1_query_str, arg2_options=None):
    """
    @brief Step E: Query Photon (photon.komoot.io/api/) for OpenStreetMap city coordinates and extent bounding box.
    @param arg1_query_str Search query string (e.g. 'Sheffield, United Kingdom').
    @param arg2_options Optional dictionary with expected_iso2 filter.
    @return Dictionary with lon, lat, extent, osm_id, osm_type, name, countrycode, or None.
    """
    #Convert from parameters
    query_str = str(arg1_query_str or "").strip()
    options = arg2_options if isinstance(arg2_options, dict) else {}

    #Initialise options
    if "expected_iso2" not in options:
      options["expected_iso2"] = None

    #Declare local instance variables
    best_feat = None
    cache_key = ""
    expected_iso2 = str(options["expected_iso2"]).upper() if options["expected_iso2"] else ""
    feats = []
    parsed_hit = None

    if not query_str:
      return None

    cache_key = f"{query_str}||{expected_iso2}"
    if cache_key in self.photon_cache_obj:
      return self.photon_cache_obj[cache_key]

    try:
      resp = self.session.get(
        self.photon_url,
        params={"lang": "en", "limit": 8, "q": query_str},
        timeout=25
      )
      if resp.status_code == 200:
        feats = resp.json().get("features", [])
        for i in range(len(feats)):
          local_f = feats[i]
          local_props = local_f.get("properties", {})
          local_cc = str(local_props.get("countrycode", "")).upper()
          local_osm_val = str(local_props.get("osm_value", "")).lower()
          if expected_iso2 and local_cc and local_cc != expected_iso2:
            continue
          if local_osm_val in ("city", "town", "municipality", "borough", "suburb", "village", "quarter", "district"):
            best_feat = local_f
            break
        if best_feat is None:
          for i in range(len(feats)):
            local_f = feats[i]
            local_props = local_f.get("properties", {})
            local_cc = str(local_props.get("countrycode", "")).upper()
            if expected_iso2 and local_cc and local_cc != expected_iso2:
              continue
            best_feat = local_f
            break
        if best_feat is None and feats and not expected_iso2:
          best_feat = feats[0]

        if best_feat is not None:
          coords = best_feat.get("geometry", {}).get("coordinates", [])
          props = best_feat.get("properties", {})
          if len(coords) >= 2:
            parsed_hit = {
              "countrycode": str(props.get("countrycode", "")),
              "extent": props.get("extent"),
              "lat": float(coords[1]),
              "lon": float(coords[0]),
              "name": str(props.get("name", "")),
              "osm_id": props.get("osm_id"),
              "osm_type": str(props.get("osm_type", "")),
              "osm_value": str(props.get("osm_value", ""))
            }
    except Exception as local_err:
      sys.stderr.write(f"Console error: Photon OSM lookup failed for '{query_str}': {local_err}\n")

    self.photon_cache_obj[cache_key] = parsed_hit
    self.saveJsonCache(self.photon_cache_path, self.photon_cache_obj)

    #Return statement
    return parsed_hit


  def F_fetchNominatimCityPoint (self, arg1_query_str):
    """
    @brief Step F: Fetch exact city-centre (lon, lat) and bounding box from Nominatim OpenStreetMap search.
    @param arg1_query_str City search query string (e.g. 'Allentown, Pennsylvania, United States').
    @return Dictionary with lon, lat, extent, osm_id, osm_type, or None.
    """
    #Convert from parameters
    query_str = str(arg1_query_str or "").strip()

    #Declare local instance variables
    cache_key = f"city_pt::{query_str}"
    elapsed = 0.0
    items = []
    pt_hit = None

    if not query_str:
      return None

    if cache_key in self.nominatim_cache_obj:
      return self.nominatim_cache_obj[cache_key]

    elapsed = time.time() - self.last_nominatim_ts
    if elapsed < 1.05:
      time.sleep(1.05 - elapsed)

    try:
      resp = self.session.get(
        self.nominatim_url,
        params={"addressdetails": 1, "format": "json", "limit": 8, "q": query_str},
        timeout=25
      )
      self.last_nominatim_ts = time.time()
      if resp.status_code == 200:
        items = resp.json()
        if items:
          chosen_item = None
          for i in range(len(items)):
            local_it = items[i]
            addr_t = str(local_it.get("addresstype") or "").lower()
            it_t = str(local_it.get("type") or "").lower()
            if (
              addr_t in ("city", "town", "municipality", "borough", "village", "suburb")
              or it_t in ("city", "town", "municipality", "borough", "village", "suburb")
            ):
              chosen_item = local_it
              break
          if chosen_item is None:
            for i in range(len(items)):
              local_it = items[i]
              addr_t = str(local_it.get("addresstype") or "").lower()
              if addr_t not in ("country", "state", "province", "region", "county", "state_district"):
                chosen_item = local_it
                break
          if chosen_item is None:
            chosen_item = items[0]
          ext = None
          bb = chosen_item.get("boundingbox")
          if isinstance(bb, list) and len(bb) == 4:
            s_lat, n_lat, w_lon, e_lon = float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])
            ext = [w_lon, n_lat, e_lon, s_lat]
          pt_hit = {
            "extent": ext,
            "lat": float(chosen_item["lat"]),
            "lon": float(chosen_item["lon"]),
            "osm_id": chosen_item.get("osm_id"),
            "osm_type": str(chosen_item.get("osm_type") or "")
          }
    except Exception as local_err:
      sys.stderr.write(f"Console error: Nominatim city point lookup failed for '{query_str}': {local_err}\n")

    self.nominatim_cache_obj[cache_key] = pt_hit
    self.saveJsonCache(self.nominatim_cache_path, self.nominatim_cache_obj)

    #Return statement
    return pt_hit


  def downloadUrlToFile (self, arg1_url, arg2_dest_path, arg3_options=None):
    """
    @brief Download an HTTP URL to disk atomically with retry support.
    @param arg1_url Source HTTPS URL.
    @param arg2_dest_path Local file path to write.
    @param arg3_options Optional dictionary with quiet_404 boolean.
    @return Boolean True upon HTTP 200 download.
    """
    #Convert from parameters
    url = str(arg1_url or "").strip()
    dest_path = str(arg2_dest_path or "").strip()
    options = arg3_options if isinstance(arg3_options, dict) else {}

    #Initialise options
    if "quiet_404" not in options:
      options["quiet_404"] = False

    #Declare local instance variables
    tmp_path = f"{dest_path}.part"

    if not url or not dest_path:
      return False

    for i in range(3):
      try:
        resp = self.session.get(url, timeout=120)
        if resp.status_code == 200 and resp.content:
          os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
          with open(tmp_path, "wb") as local_fh:
            local_fh.write(resp.content)
          os.replace(tmp_path, dest_path)
          return True
        elif resp.status_code == 404 and options["quiet_404"]:
          return False
      except Exception as local_err:
        if i == 2 and not options["quiet_404"]:
          sys.stderr.write(f"Console error: failed downloading {url}: {local_err}\n")
        time.sleep(1.0*(i + 1))

    #Return statement
    return False


  def healFeatureCollectionStrings (self, arg1_fc_obj):
    """
    @brief Heal Latin-1-as-UTF-8 mojibake across all feature property dictionaries.
    @param arg1_fc_obj GeoJSON FeatureCollection dictionary modified in place.
    @return Modified FeatureCollection dictionary.
    """
    #Convert from parameters
    fc_obj = arg1_fc_obj if isinstance(arg1_fc_obj, dict) else {}

    #Declare local instance variables
    feats = fc_obj.get("features", [])

    for i in range(len(feats)):
      local_props = feats[i].get("properties")
      if isinstance(local_props, dict):
        for local_k, local_v in list(local_props.items()):
          if isinstance(local_v, str) and ("Ã" in local_v or "Â" in local_v):
            try:
              local_props[local_k] = local_v.encode("latin1").decode("utf-8")
            except Exception:
              pass

    #Return statement
    return fc_obj


  def loadApiCaches (self):
    """
    @brief Load persisted Wikipedia, Photon and Nominatim JSON caches if present in cache_dir.
    """
    if os.path.exists(self.wiki_cache_path):
      self.wiki_cache_obj = self.readGeoJsonDisk(self.wiki_cache_path)
    if os.path.exists(self.photon_cache_path):
      self.photon_cache_obj = self.readGeoJsonDisk(self.photon_cache_path)
    if os.path.exists(self.nominatim_cache_path):
      self.nominatim_cache_obj = self.readGeoJsonDisk(self.nominatim_cache_path)


  def normaliseAsciiSlug (self, arg1_text):
    """
    @brief Transliterate accented/Germanic/Slavic characters and normalise a string into an ASCII snake_case slug.
    @param arg1_text Input string.
    @return Clean snake_case ASCII string.
    """
    #Convert from parameters
    text = str(arg1_text or "").strip()

    #Declare local instance variables
    ascii_chars = []
    decomposed = ""
    out_slug = ""

    if not text:
      return ""

    text = (
      text.replace("ß", "ss")
      .replace("Æ", "Ae")
      .replace("æ", "ae")
      .replace("Ø", "O")
      .replace("ø", "o")
      .replace("Ł", "L")
      .replace("ł", "l")
      .replace("Đ", "D")
      .replace("đ", "d")
    )
    decomposed = unicodedata.normalize("NFKD", text)
    for i in range(len(decomposed)):
      ch = decomposed[i]
      if not unicodedata.combining(ch):
        if ch.isalnum() and ch.isascii():
          ascii_chars.append(ch.lower())
        else:
          ascii_chars.append("_")

    out_slug = re.sub(r"_+", "_", "".join(ascii_chars))

    #Return statement
    return out_slug.strip("_")


  def parseDbfBytes (self, arg1_dbf_bytes):
    """
    @brief Parse an ESRI dBASE III/IV (.dbf) binary table into a list of property dictionaries.
    @param arg1_dbf_bytes Raw bytes of the .dbf file.
    @return List of row attribute dictionaries.
    """
    #Convert from parameters
    dbf_bytes = arg1_dbf_bytes

    #Declare local instance variables
    fields = []
    header_len = 0
    num_records = 0
    offset = 32
    pos = 0
    record_len = 0
    rows_array = []

    if not dbf_bytes or len(dbf_bytes) < 32:
      return rows_array

    num_records, header_len, record_len = struct.unpack("<IHH", dbf_bytes[4:12])
    for _ in range(256):
      if offset >= header_len - 1 or dbf_bytes[offset] == 0x0D:
        break
      field_desc = dbf_bytes[offset:offset + 32]
      field_name = field_desc[:11].split(b"\x00")[0].decode("ascii", errors="ignore")
      field_type = chr(field_desc[11])
      field_len = field_desc[16]
      fields.append((field_name, field_type, field_len))
      offset = offset + 32

    pos = header_len
    for _ in range(num_records):
      if pos + record_len > len(dbf_bytes):
        break
      rec = dbf_bytes[pos:pos + record_len]
      pos = pos + record_len
      if rec[0:1] == b"*":
        continue
      fpos = 1
      row_obj = {}
      for x in range(len(fields)):
        fname, ftype, flen = fields[x]
        raw_val = rec[fpos:fpos + flen]
        fpos = fpos + flen
        txt_val = raw_val.decode("utf-8", errors="replace").strip()
        if ftype in ("N", "F"):
          try:
            row_obj[fname] = float(txt_val) if "." in txt_val else int(txt_val or 0)
          except Exception:
            row_obj[fname] = txt_val
        else:
          row_obj[fname] = txt_val
      rows_array.append(row_obj)

    #Return statement
    return rows_array


  def parseShapefileZip (self, arg1_zip_path, arg2_shp_member, arg3_dbf_member):
    """
    @brief Parse a zipped WGS84 ESRI Polygon Shapefile (.shp + .dbf) into a GeoJSON FeatureCollection.
    @param arg1_zip_path Path to .zip archive on disk.
    @param arg2_shp_member Filename of .shp inside archive.
    @param arg3_dbf_member Filename of .dbf inside archive.
    @return GeoJSON FeatureCollection dictionary.
    """
    #Convert from parameters
    zip_path = str(arg1_zip_path or "")
    shp_member = str(arg2_shp_member or "")
    dbf_member = str(arg3_dbf_member or "")

    #Declare local instance variables
    dbf_rows = []
    features_array = []
    offset = 100
    rec_idx = 0
    shp_bytes = b""

    if not os.path.exists(zip_path):
      return {"features": [], "type": "FeatureCollection"}

    with zipfile.ZipFile(zip_path, "r") as local_zf:
      names = local_zf.namelist()
      if shp_member not in names:
        shp_candidates = [n for n in names if n.lower().endswith(".shp")]
        shp_member = shp_candidates[0] if shp_candidates else ""
      if dbf_member not in names:
        dbf_candidates = [n for n in names if n.lower().endswith(".dbf")]
        dbf_member = dbf_candidates[0] if dbf_candidates else ""
      shp_bytes = local_zf.read(shp_member)
      dbf_rows = self.parseDbfBytes(local_zf.read(dbf_member))

    for _ in range(len(dbf_rows) + 1000):
      if offset + 8 > len(shp_bytes):
        break
      _, content_len_words = struct.unpack(">II", shp_bytes[offset:offset + 8])
      content_bytes_len = content_len_words*2
      rec_start = offset + 8
      rec_end = rec_start + content_bytes_len
      if rec_end > len(shp_bytes):
        break
      shape_type = struct.unpack("<I", shp_bytes[rec_start:rec_start + 4])[0]
      props_obj = dbf_rows[rec_idx] if rec_idx < len(dbf_rows) else {}
      rec_idx = rec_idx + 1
      offset = rec_end

      if shape_type == 0:
        continue
      if shape_type in (5, 15, 25):
        num_parts, num_points = struct.unpack("<II", shp_bytes[rec_start + 36:rec_start + 44])
        parts_start = rec_start + 44
        pts_start = parts_start + 4*num_parts
        part_indices = list(struct.unpack(f"<{num_parts}i", shp_bytes[parts_start:pts_start]))
        raw_pts = struct.unpack(f"<{2*num_points}d", shp_bytes[pts_start:pts_start + 16*num_points])
        rings = []
        for x in range(num_parts):
          p0 = part_indices[x]
          p1 = part_indices[x + 1] if x + 1 < num_parts else num_points
          ring = [[raw_pts[2*y], raw_pts[2*y + 1]] for y in range(p0, p1)]
          if len(ring) >= 4:
            rings.append(ring)
        if rings:
          geom_obj = self.ringsToGeoJsonMultiPolygon(rings)
          features_array.append({
            "geometry": geom_obj,
            "properties": props_obj,
            "type": "Feature"
          })

    #Return statement
    return {"features": features_array, "type": "FeatureCollection"}


  def readGeoJsonDisk (self, arg1_file_path):
    """
    @brief Fast-load a JSON/GeoJSON file from disk using orjson with stdlib json fallback.
    @param arg1_file_path Path to JSON file on disk.
    @return Parsed dictionary.
    """
    #Convert from parameters
    file_path = str(arg1_file_path or "")

    #Declare local instance variables
    parsed_obj = {}

    if not file_path or not os.path.exists(file_path):
      return parsed_obj

    try:
      with open(file_path, "rb") as local_fh:
        parsed_obj = orjson.loads(local_fh.read())
    except Exception:
      try:
        with open(file_path, "r", encoding="utf-8") as local_fh:
          parsed_obj = json.load(local_fh)
      except Exception as local_err:
        sys.stderr.write(f"Console error: failed reading JSON {file_path}: {local_err}\n")
        parsed_obj = {}

    #Return statement
    return parsed_obj if isinstance(parsed_obj, dict) else {}


  def ringsToGeoJsonMultiPolygon (self, arg1_rings_array):
    """
    @brief Classify ESRI Shapefile clockwise exterior rings and counter-clockwise interior hole rings into GeoJSON geometry.
    @param arg1_rings_array List of coordinate rings [[lon, lat], ...].
    @return GeoJSON Polygon or MultiPolygon dictionary.
    """
    #Convert from parameters
    rings_array = arg1_rings_array if isinstance(arg1_rings_array, list) else []

    #Declare local instance variables
    exteriors = []
    holes = []
    polygons = []

    for i in range(len(rings_array)):
      ring = rings_array[i]
      signed_area = 0.0
      for x in range(len(ring) - 1):
        signed_area = signed_area + (ring[x + 1][0] - ring[x][0])*(ring[x + 1][1] + ring[x][1])
      if signed_area >= 0.0:
        exteriors.append([ring])
      else:
        holes.append(ring)

    if not exteriors and holes:
      exteriors = [[h] for h in holes]
      holes = []

    for i in range(len(holes)):
      hole_pt = holes[i][0]
      assigned_idx = 0
      for x in range(len(exteriors)):
        ext_ring = exteriors[x][0]
        xs = [p[0] for p in ext_ring]
        ys = [p[1] for p in ext_ring]
        if min(xs) <= hole_pt[0] <= max(xs) and min(ys) <= hole_pt[1] <= max(ys):
          assigned_idx = x
          break
      exteriors[assigned_idx].append(holes[i])

    polygons = exteriors

    #Return statement
    return {"coordinates": polygons[0], "type": "Polygon"} if len(polygons) == 1 else {"coordinates": polygons, "type": "MultiPolygon"}


  def saveJsonCache (self, arg1_path, arg2_data_obj):
    """
    @brief Persist an API cache dictionary to disk using orjson.
    @param arg1_path Destination cache file path.
    @param arg2_data_obj Dictionary to serialise.
    """
    #Convert from parameters
    path = str(arg1_path or "")
    data_obj = arg2_data_obj if isinstance(arg2_data_obj, dict) else {}

    if not path:
      return

    try:
      with open(path, "wb") as local_fh:
        local_fh.write(orjson.dumps(data_obj))
    except Exception as local_err:
      sys.stderr.write(f"Console error: failed saving cache {path}: {local_err}\n")


  def writeGeoJsonDisk (self, arg1_path, arg2_fc_obj):
    """
    @brief Serialise a parsed FeatureCollection dictionary to disk cache.
    @param arg1_path Destination GeoJSON file path.
    @param arg2_fc_obj GeoJSON FeatureCollection dictionary.
    """
    #Convert from parameters
    path = str(arg1_path or "")
    fc_obj = arg2_fc_obj if isinstance(arg2_fc_obj, dict) else {}

    if not path:
      return

    try:
      with open(path, "wb") as local_fh:
        local_fh.write(orjson.dumps(fc_obj))
    except Exception as local_err:
      sys.stderr.write(f"Console error: failed writing GeoJSON {path}: {local_err}\n")
