"""@brief WGS84 Equirectangular scanline polygon rasteriser, morphological frontier snapper and lossless PNG exporter."""

import math
import os
import sys
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, label
from shapely.geometry import MultiPolygon, Point, Polygon, box, shape
from shapely.ops import unary_union


class EquirectangularRasteriser:
  """@brief Scanline-rasterises WGS84 GeoJSON/Shapely geometries onto a 4320x2160 Equirectangular grid with zero stray edge pixels."""

  def __init__ (self, arg1_grid_config_obj=None, arg2_frontier_config_obj=None):
    """
    @brief Initialise EquirectangularRasteriser with target pixel dimensions, lookup tables and frontier-snapping defaults.
    @param arg1_grid_config_obj Grid configuration dictionary from areal_mask_config.json5.
    @param arg2_frontier_config_obj Optional frontier_snap configuration dictionary from areal_mask_config.json5.
    """
    #Convert from parameters
    grid_config_obj = arg1_grid_config_obj if isinstance(arg1_grid_config_obj, dict) else {}
    frontier_config_obj = arg2_frontier_config_obj if isinstance(arg2_frontier_config_obj, dict) else {}

    #Declare local instance variables
    self.crs = str(grid_config_obj.get("crs", "EPSG:4326"))
    self.default_max_pocket_px = int(frontier_config_obj.get("max_pocket_px", 48))
    self.default_min_island_ratio = float(frontier_config_obj.get("min_island_coverage_ratio", 0.25))
    self.default_min_speck_px = int(frontier_config_obj.get("min_speck_px", 4))
    self.default_snap_radius_px = int(frontier_config_obj.get("snap_radius_px", 5))
    self.height = int(grid_config_obj.get("height", 2160))
    self.pixels_per_degree = float(grid_config_obj.get("pixels_per_degree", 12.0))
    self.width = self.getConfiguredWidth(grid_config_obj)
    self.lat_centres = 90.0 - (np.arange(self.height, dtype=np.float64) + 0.5)/self.pixels_per_degree
    self.lon_centres = -180.0 + (np.arange(self.width, dtype=np.float64) + 0.5)/self.pixels_per_degree
    self.total_pixels = self.width*self.height


  def A_rasteriseGeometry (self, arg1_geometry_obj, arg2_options=None):
    """
    @brief Step A: Scanline-rasterise a GeoJSON dict, Shapely geometry or list of geometries to sorted flat pixel indices.
    @param arg1_geometry_obj GeoJSON geometry dict, Feature dict, Shapely geometry or list thereof.
    @param arg2_options Optional dictionary with fallback_lonlat and ensure_min_pixel (default True).
    @return Sorted 1D numpy int32 array of flat pixel indices (y*width + x).
    """
    #Convert from parameters
    geometry_obj = arg1_geometry_obj
    options = arg2_options if isinstance(arg2_options, dict) else {}

    #Initialise options
    if "ensure_min_pixel" not in options:
      options["ensure_min_pixel"] = True
    if "fallback_lonlat" not in options:
      options["fallback_lonlat"] = None

    #Declare local instance variables
    combined_array = None
    empty_array = np.zeros(0, dtype=np.int32)
    fallback_pt = options["fallback_lonlat"]
    flat_indices_list = []
    merged_geom = None
    poly_list = []
    rep_point = None

    poly_list = self.extractPolygons(geometry_obj)
    if not poly_list:
      if fallback_pt is not None and len(fallback_pt) >= 2:
        return self.lonLatToFlatIndexArray(float(fallback_pt[0]), float(fallback_pt[1]))
      if options["ensure_min_pixel"]:
        sys.stderr.write("Console error: empty geometry passed to A_rasteriseGeometry.\n")
      return empty_array

    for i in range(len(poly_list)):
      local_poly = poly_list[i]
      local_parts = self.splitAntimeridianPolygon(local_poly)
      for x in range(len(local_parts)):
        local_idx = self.rasteriseSinglePolygon(local_parts[x])
        if local_idx.size > 0:
          flat_indices_list.append(local_idx)

    if flat_indices_list:
      combined_array = np.unique(np.concatenate(flat_indices_list))
    else:
      combined_array = empty_array

    if combined_array.size == 0 and options["ensure_min_pixel"]:
      try:
        merged_geom = unary_union(poly_list)
        rep_point = merged_geom.representative_point()
        combined_array = self.lonLatToFlatIndexArray(rep_point.x, rep_point.y)
      except Exception:
        if fallback_pt is not None and len(fallback_pt) >= 2:
          combined_array = self.lonLatToFlatIndexArray(float(fallback_pt[0]), float(fallback_pt[1]))
        else:
          local_b = poly_list[0].bounds
          combined_array = self.lonLatToFlatIndexArray(0.5*(local_b[0] + local_b[2]), 0.5*(local_b[1] + local_b[3]))

    #Return statement
    return combined_array


  def B_exportRgbPng (self, arg1_rgb_buffer, arg2_output_path):
    """
    @brief Step B: Export a (height, width, 3) uint8 RGB numpy buffer as a lossless PNG image.
    @param arg1_rgb_buffer Numpy uint8 array of shape (2160, 4320, 3).
    @param arg2_output_path Destination .png file path.
    @return Boolean True upon successful write.
    """
    #Convert from parameters
    rgb_buffer = arg1_rgb_buffer
    output_path = str(arg2_output_path or "")

    #Declare local instance variables
    img_obj = None
    parent_dir = ""

    if not isinstance(rgb_buffer, np.ndarray) or rgb_buffer.shape != (self.height, self.width, 3):
      sys.stderr.write(f"Console error: invalid RGB buffer shape for PNG export: {getattr(rgb_buffer, 'shape', None)}\n")
      return False
    if not output_path:
      sys.stderr.write("Console error: empty output_path passed to B_exportRgbPng.\n")
      return False

    parent_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(parent_dir, exist_ok=True)
    img_obj = Image.fromarray(rgb_buffer, mode="RGB")
    img_obj.save(output_path, format="PNG", compress_level=6)

    #Return statement
    return True


  def clipIndicesWithFallback (self, arg1_flat_indices, arg2_clip_indices):
    """
    @brief Intersect a flat pixel index mask with a target mask, snapping to the nearest target pixel if small territory drops to 0.
    @param arg1_flat_indices Sorted 1D numpy int32 array of source entity pixels.
    @param arg2_clip_indices Sorted 1D numpy int32 array of allowed target pixels.
    @return Sorted 1D numpy int32 array of clipped pixel indices.
    """
    #Convert from parameters
    flat_indices = arg1_flat_indices
    clip_indices = arg2_clip_indices

    #Declare local instance variables
    best_i = 0
    clipped = None
    cx = 0.0
    cy = 0.0
    dists = None
    tx = None
    ty = None

    if not isinstance(flat_indices, np.ndarray) or flat_indices.size == 0:
      return np.zeros(0, dtype=np.int32)
    if not isinstance(clip_indices, np.ndarray) or clip_indices.size == 0:
      return flat_indices

    clipped = np.intersect1d(flat_indices, clip_indices, assume_unique=True)
    if clipped.size > 0:
      return clipped

    cx = float((flat_indices % self.width).mean())
    cy = float((flat_indices // self.width).mean())
    tx = (clip_indices % self.width).astype(np.float64)
    ty = (clip_indices // self.width).astype(np.float64)
    dists = (tx - cx)*(tx - cx) + (ty - cy)*(ty - cy)
    best_i = int(np.argmin(dists))

    #Return statement
    return np.array([int(clip_indices[best_i])], dtype=np.int32)


  def computeMaskMetrics (self, arg1_flat_indices):
    """
    @brief Compute pixel count, pixel bounding box, WGS84 bounding box and WGS84 centroid from flat pixel indices.
    @param arg1_flat_indices Sorted 1D numpy int32 array of flat pixel indices.
    @return Dictionary containing pixel_count, bbox_px, bbox_wgs84 and centroid_wgs84.
    """
    #Convert from parameters
    flat_indices = arg1_flat_indices

    #Declare local instance variables
    cx_deg = 0.0
    cy_deg = 0.0
    east_deg = 0.0
    max_x = 0
    max_y = 0
    min_x = 0
    min_y = 0
    north_deg = 0.0
    south_deg = 0.0
    west_deg = 0.0
    xs = None
    ys = None

    if not isinstance(flat_indices, np.ndarray) or flat_indices.size == 0:
      return {
        "bbox_px": [0, 0, 0, 0],
        "bbox_wgs84": [0.0, 0.0, 0.0, 0.0],
        "centroid_wgs84": [0.0, 0.0],
        "pixel_count": 0
      }

    ys = flat_indices // self.width
    xs = flat_indices % self.width
    min_x = int(xs.min())
    max_x = int(xs.max())
    min_y = int(ys.min())
    max_y = int(ys.max())

    west_deg = round(min_x/self.pixels_per_degree - 180.0, 5)
    east_deg = round((max_x + 1)/self.pixels_per_degree - 180.0, 5)
    north_deg = round(90.0 - min_y/self.pixels_per_degree, 5)
    south_deg = round(90.0 - (max_y + 1)/self.pixels_per_degree, 5)
    cx_deg = round((float(xs.mean()) + 0.5)/self.pixels_per_degree - 180.0, 5)
    cy_deg = round(90.0 - (float(ys.mean()) + 0.5)/self.pixels_per_degree, 5)

    #Return statement
    return {
      "bbox_px": [min_x, min_y, max_x, max_y],
      "bbox_wgs84": [west_deg, south_deg, east_deg, north_deg],
      "centroid_wgs84": [cx_deg, cy_deg],
      "pixel_count": int(flat_indices.size)
    }


  def extractPolygons (self, arg1_geometry_obj):
    """
    @brief Recursively unpack GeoJSON dicts, Feature dicts or Shapely geometries into valid Shapely Polygons.
    @param arg1_geometry_obj Input geometry container.
    @return List of Shapely Polygon objects.
    """
    #Convert from parameters
    geometry_obj = arg1_geometry_obj

    #Declare local instance variables
    geom = None
    polygons_array = []

    if geometry_obj is None:
      return polygons_array

    if isinstance(geometry_obj, list):
      for i in range(len(geometry_obj)):
        polygons_array.extend(self.extractPolygons(geometry_obj[i]))
      return polygons_array

    if isinstance(geometry_obj, dict):
      if geometry_obj.get("type") == "FeatureCollection":
        local_feats = geometry_obj.get("features", [])
        for i in range(len(local_feats)):
          polygons_array.extend(self.extractPolygons(local_feats[i]))
        return polygons_array
      elif geometry_obj.get("type") == "Feature":
        return self.extractPolygons(geometry_obj.get("geometry"))
      else:
        try:
          geom = shape(geometry_obj)
        except Exception:
          return polygons_array
    else:
      geom = geometry_obj

    if geom is None or geom.is_empty:
      return polygons_array

    if not geom.is_valid:
      try:
        geom = geom.buffer(0)
      except Exception:
        pass

    if isinstance(geom, Polygon):
      if not geom.is_empty:
        polygons_array.append(geom)
    elif isinstance(geom, MultiPolygon):
      local_geoms = list(geom.geoms)
      for i in range(len(local_geoms)):
        if not local_geoms[i].is_empty:
          polygons_array.append(local_geoms[i])
    elif hasattr(geom, "geoms"):
      local_geoms = list(geom.geoms)
      for i in range(len(local_geoms)):
        polygons_array.extend(self.extractPolygons(local_geoms[i]))
    elif isinstance(geom, Point):
      polygons_array.append(geom.buffer(0.05))

    #Return statement
    return polygons_array


  def getConfiguredWidth (self, arg1_grid_config_obj):
    """
    @brief Read validated grid width from configuration dictionary.
    @param arg1_grid_config_obj Grid configuration dictionary.
    @return Positive integer width (default 4320).
    """
    #Convert from parameters
    grid_config_obj = arg1_grid_config_obj if isinstance(arg1_grid_config_obj, dict) else {}

    #Return statement
    return int(grid_config_obj.get("width", 4320))


  def lonLatToFlatIndexArray (self, arg1_lon, arg2_lat):
    """
    @brief Convert a single WGS84 (lon, lat) coordinate into a 1-element int32 flat pixel index array.
    @param arg1_lon Longitude in degrees [-180, 180].
    @param arg2_lat Latitude in degrees [-90, 90].
    @return 1D numpy int32 array with 1 pixel index.
    """
    #Convert from parameters
    lon = float(arg1_lon)
    lat = float(arg2_lat)

    #Declare local instance variables
    px_x = 0
    px_y = 0
    wrapped_lon = ((lon + 180.0) % 360.0) - 180.0

    px_x = min(self.width - 1, max(0, int(math.floor((wrapped_lon + 180.0)*self.pixels_per_degree))))
    px_y = min(self.height - 1, max(0, int(math.floor((90.0 - lat)*self.pixels_per_degree))))

    #Return statement
    return np.array([px_y*self.width + px_x], dtype=np.int32)


  def rasteriseBbox (self, arg1_west, arg2_south, arg3_east, arg4_north):
    """
    @brief Rasterise a WGS84 bounding box [west, south, east, north] directly to flat pixel indices.
    @param arg1_west Western longitude in degrees.
    @param arg2_south Southern latitude in degrees.
    @param arg3_east Eastern longitude in degrees.
    @param arg4_north Northern latitude in degrees.
    @return Sorted 1D numpy int32 array of flat pixel indices.
    """
    #Convert from parameters
    west = float(arg1_west)
    south = float(arg2_south)
    east = float(arg3_east)
    north = float(arg4_north)

    #Declare local instance variables
    bbox_poly = None

    if east < west:
      part_a = box(west, south, 180.0, north)
      part_b = box(-180.0, south, east, north)
      return self.A_rasteriseGeometry([part_a, part_b], {"fallback_lonlat": [west, 0.5*(south + north)]})

    bbox_poly = box(max(-180.0, west), max(-90.0, south), min(180.0, east), min(90.0, north))

    #Return statement
    return self.A_rasteriseGeometry(bbox_poly, {"fallback_lonlat": [0.5*(west + east), 0.5*(south + north)]})


  def rasteriseSinglePolygon (self, arg1_polygon):
    """
    @brief Scanline-rasterise a single non-dateline-crossing Shapely Polygon via exact half-open float64 pixel-centre containment.
    @param arg1_polygon Shapely Polygon within [-180, 180] x [-90, 90].
    @return Sorted 1D numpy int32 array of flat pixel indices with zero shared-edge overlap across adjacent polygons.
    """
    #Convert from parameters
    polygon = arg1_polygon

    #Declare local instance variables
    bounds = None
    dx_dy = None
    empty_array = np.zeros(0, dtype=np.int32)
    max_gy = 0
    min_gy = 0
    rings_list = []
    row_spans = []
    x_hi = None
    x_hi_list = []
    x_lo = None
    x_lo_list = []
    y_hi = None
    y_hi_list = []
    y_lo = None
    y_lo_list = []

    if polygon is None or polygon.is_empty:
      return empty_array

    bounds = polygon.bounds
    min_gy = max(0, int(math.floor((90.0 - bounds[3])*self.pixels_per_degree)) - 1)
    max_gy = min(self.height - 1, int(math.ceil((90.0 - bounds[1])*self.pixels_per_degree)) + 1)
    if max_gy < min_gy:
      return empty_array

    rings_list.append(np.asarray(polygon.exterior.coords, dtype=np.float64))
    for i in range(len(polygon.interiors)):
      rings_list.append(np.asarray(polygon.interiors[i].coords, dtype=np.float64))

    for i in range(len(rings_list)):
      local_r = rings_list[i]
      if local_r.shape[0] < 4:
        continue
      ax = local_r[:-1, 0]
      ay = local_r[:-1, 1]
      bx = local_r[1:, 0]
      by = local_r[1:, 1]
      non_horiz = ay != by
      if not np.any(non_horiz):
        continue
      ax = ax[non_horiz]
      ay = ay[non_horiz]
      bx = bx[non_horiz]
      by = by[non_horiz]
      swap_mask = ay > by
      x_lo_list.append(np.where(swap_mask, bx, ax))
      y_lo_list.append(np.where(swap_mask, by, ay))
      x_hi_list.append(np.where(swap_mask, ax, bx))
      y_hi_list.append(np.where(swap_mask, ay, by))

    if not x_lo_list:
      return empty_array

    x_lo = np.concatenate(x_lo_list)
    y_lo = np.concatenate(y_lo_list)
    x_hi = np.concatenate(x_hi_list)
    y_hi = np.concatenate(y_hi_list)
    dx_dy = (x_hi - x_lo)/(y_hi - y_lo)

    for i in range(min_gy, max_gy + 1):
      yc = self.lat_centres[i]
      active_mask = (y_lo <= yc) & (yc < y_hi)
      if not np.any(active_mask):
        continue
      x_ints = x_lo[active_mask] + (yc - y_lo[active_mask])*dx_dy[active_mask]
      x_ints.sort()
      num_pairs = x_ints.size // 2
      if num_pairs == 0:
        continue
      gx_starts = np.searchsorted(self.lon_centres, x_ints[0:2*num_pairs:2], side="left")
      gx_ends = np.searchsorted(self.lon_centres, x_ints[1:2*num_pairs:2], side="left")
      row_base = i*self.width
      for x in range(num_pairs):
        local_s = int(gx_starts[x])
        local_e = int(gx_ends[x])
        if local_e > local_s:
          row_spans.append(row_base + np.arange(local_s, local_e, dtype=np.int32))

    #Return statement
    return np.concatenate(row_spans) if row_spans else empty_array


  def snapHistoricalFrontierToHost (self, arg1_raw_indices, arg2_host_indices, arg3_options=None):
    """
    @brief Snap a coarse historical or GADM mask onto an exact Natural Earth 10m host mask, eliminating coastal shortfall strips and graze specks while preserving true inland frontiers.
    @param arg1_raw_indices Sorted 1D int32 flat pixel array of the raw historical/regional polygon.
    @param arg2_host_indices Sorted 1D int32 flat pixel array of the canonical Natural Earth 10m host countries.
    @param arg3_options Optional dictionary overriding snap_radius_px, max_pocket_px, min_speck_px or min_island_coverage_ratio.
    @return Sorted 1D int32 flat pixel array strictly within arg2_host_indices with crisp coastlines and borders.
    """
    #Convert from parameters
    raw_indices = arg1_raw_indices
    host_indices = arg2_host_indices
    options = arg3_options if isinstance(arg3_options, dict) else {}

    #Initialise options
    if "max_pocket_px" not in options:
      options["max_pocket_px"] = self.default_max_pocket_px
    if "min_island_coverage_ratio" not in options:
      options["min_island_coverage_ratio"] = self.default_min_island_ratio
    if "min_speck_px" not in options:
      options["min_speck_px"] = self.default_min_speck_px
    if "snap_radius_px" not in options:
      options["snap_radius_px"] = self.default_snap_radius_px

    #Declare local instance variables
    c0_sub = None
    c_deep = None
    c_kept = None
    conn_struct = np.ones((3, 3), dtype=np.int32)
    dist_c = None
    dist_p = None
    final_indices = None
    h_sub_h = 0
    h_sub_w = 0
    host_labels = None
    host_sub = None
    hx = None
    hy = None
    max_pocket_px = int(options["max_pocket_px"])
    min_island_ratio = float(options["min_island_coverage_ratio"])
    min_speck_px = int(options["min_speck_px"])
    num_host_comps = 0
    num_pocket_comps = 0
    p0_clipped = None
    p0_sub = None
    p_final_sub = None
    pad = 0
    pocket_labels = None
    snap_radius_px = max(1, int(options["snap_radius_px"]))
    untouched_sub = None
    x0 = 0
    x1 = 0
    y0 = 0
    y1 = 0

    if not isinstance(raw_indices, np.ndarray) or raw_indices.size == 0:
      return np.zeros(0, dtype=np.int32)
    if not isinstance(host_indices, np.ndarray) or host_indices.size == 0:
      return raw_indices

    p0_clipped = np.intersect1d(raw_indices, host_indices, assume_unique=True)
    if p0_clipped.size == 0:
      return self.clipIndicesWithFallback(raw_indices, host_indices)

    hx = host_indices % self.width
    hy = host_indices // self.width
    pad = snap_radius_px + 3
    if int(hx.max() - hx.min()) > 3200:
      x0 = 0
      x1 = self.width
    else:
      x0 = max(0, int(hx.min()) - pad)
      x1 = min(self.width, int(hx.max()) + 1 + pad)
    y0 = max(0, int(hy.min()) - pad)
    y1 = min(self.height, int(hy.max()) + 1 + pad)

    h_sub_h = y1 - y0
    h_sub_w = x1 - x0
    host_sub = np.zeros((h_sub_h, h_sub_w), dtype=bool)
    p0_sub = np.zeros((h_sub_h, h_sub_w), dtype=bool)
    host_sub[hy - y0, hx - x0] = True
    p0_sub[(p0_clipped // self.width) - y0, (p0_clipped % self.width) - x0] = True

    host_labels, num_host_comps = label(host_sub, structure=conn_struct)
    if num_host_comps > 0:
      comp_total = np.bincount(host_labels.ravel(), minlength=num_host_comps + 1)
      comp_overlap = np.bincount(host_labels[p0_sub].ravel(), minlength=num_host_comps + 1)

      speck_ids = np.flatnonzero(
        (comp_overlap > 0)
        & (comp_overlap <= min_speck_px)
        & (comp_overlap < min_island_ratio*np.maximum(1, comp_total))
      )
      if speck_ids.size > 0:
        speck_lut = np.zeros(num_host_comps + 1, dtype=bool)
        speck_lut[speck_ids] = True
        p0_sub[speck_lut[host_labels]] = False
        comp_overlap[speck_ids] = 0

      absorb_ids = np.flatnonzero(
        (comp_overlap > min_speck_px)
        & (comp_overlap >= 0.70*np.maximum(1, comp_total))
        & ((comp_total - comp_overlap) <= max_pocket_px)
      )
      if absorb_ids.size > 0:
        absorb_lut = np.zeros(num_host_comps + 1, dtype=bool)
        absorb_lut[absorb_ids] = True
        p0_sub[absorb_lut[host_labels]] = True
        comp_overlap[absorb_ids] = comp_total[absorb_ids]

      untouched_lut = np.zeros(num_host_comps + 1, dtype=bool)
      untouched_lut[comp_overlap == 0] = True
      untouched_lut[0] = False
      untouched_sub = untouched_lut[host_labels]
    else:
      untouched_sub = np.zeros((h_sub_h, h_sub_w), dtype=bool)

    if not np.any(p0_sub):
      return self.clipIndicesWithFallback(raw_indices, host_indices)

    c0_sub = host_sub & (~p0_sub)
    if np.any(c0_sub):
      dist_p = distance_transform_edt(~p0_sub)
      c_deep = c0_sub & (~untouched_sub) & (dist_p > float(snap_radius_px))
      if np.any(c_deep):
        dist_c = distance_transform_edt(~c_deep)
        c_kept = c0_sub & (untouched_sub | (dist_c <= float(snap_radius_px) + 0.35))
      else:
        c_kept = c0_sub & untouched_sub

      non_island_kept = c_kept & (~untouched_sub)
      if max_pocket_px > 0 and np.any(non_island_kept):
        pocket_labels, num_pocket_comps = label(non_island_kept, structure=conn_struct)
        if num_pocket_comps > 0:
          pocket_sizes = np.bincount(pocket_labels.ravel(), minlength=num_pocket_comps + 1)
          small_pockets = np.flatnonzero((pocket_sizes > 0) & (pocket_sizes < max_pocket_px))
          small_pockets = small_pockets[small_pockets > 0]
          if small_pockets.size > 0:
            drop_lut = np.zeros(num_pocket_comps + 1, dtype=bool)
            drop_lut[small_pockets] = True
            c_kept[drop_lut[pocket_labels]] = False
    else:
      c_kept = np.zeros((h_sub_h, h_sub_w), dtype=bool)

    p_final_sub = host_sub & (~c_kept)
    fy, fx = np.nonzero(p_final_sub)
    if fy.size == 0:
      return self.clipIndicesWithFallback(raw_indices, host_indices)

    final_indices = ((fy.astype(np.int32) + y0)*self.width + (fx.astype(np.int32) + x0)).astype(np.int32)
    final_indices.sort()

    #Return statement
    return final_indices


  def snapPartitionToTargetMask (self, arg1_members_map, arg2_target_indices, arg3_options=None):
    """
    @brief Clip a map of sub-division masks to a canonical parent mask, optionally enforcing pairwise disjointness and filling uncovered coastal pixels.
    @param arg1_members_map Dictionary mapping entity_id -> sorted 1D int32 flat pixel array.
    @param arg2_target_indices Sorted 1D int32 flat pixel array of the canonical parent territory.
    @param arg3_options Optional dictionary with disjoint (default False), fill_uncovered (default True) and priority_keys (default []).
    @return Dictionary mapping entity_id -> snapped sorted 1D int32 flat pixel array.
    """
    #Convert from parameters
    members_map = arg1_members_map if isinstance(arg1_members_map, dict) else {}
    target_indices = arg2_target_indices
    options = arg3_options if isinstance(arg3_options, dict) else {}

    #Initialise options
    if "disjoint" not in options:
      options["disjoint"] = False
    if "fill_uncovered" not in options:
      options["fill_uncovered"] = True
    if "priority_keys" not in options:
      options["priority_keys"] = []

    #Declare local instance variables
    claimed_px = np.zeros(0, dtype=np.int32)
    covered_owner = []
    covered_px = []
    disjoint_flag = bool(options["disjoint"])
    eids_ordered = []
    fill_uncovered = bool(options["fill_uncovered"])
    out_map = {}
    priority_list = options["priority_keys"] if isinstance(options["priority_keys"], list) else []
    seen_eids = set()
    uncovered_px = None

    for i in range(len(priority_list)):
      local_pk = str(priority_list[i])
      if local_pk in members_map and local_pk not in seen_eids:
        eids_ordered.append(local_pk)
        seen_eids.add(local_pk)
    for local_k in sorted(members_map.keys()):
      if local_k not in seen_eids:
        eids_ordered.append(local_k)
        seen_eids.add(local_k)

    if not isinstance(target_indices, np.ndarray) or target_indices.size == 0 or not eids_ordered:
      return dict(members_map)

    for i in range(len(eids_ordered)):
      local_eid = eids_ordered[i]
      local_clipped = self.clipIndicesWithFallback(members_map[local_eid], target_indices)
      if disjoint_flag and claimed_px.size > 0 and local_clipped.size > 1:
        local_dedup = np.setdiff1d(local_clipped, claimed_px, assume_unique=True)
        if local_dedup.size > 0:
          local_clipped = local_dedup
      out_map[local_eid] = local_clipped
      if local_clipped.size > 0:
        if disjoint_flag:
          claimed_px = np.unique(np.concatenate([claimed_px, local_clipped])) if claimed_px.size > 0 else local_clipped
        covered_px.append(local_clipped)
        covered_owner.append(np.full(local_clipped.size, i, dtype=np.int32))

    if fill_uncovered and covered_px:
      all_cov = np.concatenate(covered_px)
      all_own = np.concatenate(covered_owner)
      uncovered_px = np.setdiff1d(target_indices, np.unique(all_cov), assume_unique=True)
      if uncovered_px.size > 0:
        cov_x = (all_cov % self.width).astype(np.int32)
        cov_y = (all_cov // self.width).astype(np.int32)
        unc_x = (uncovered_px % self.width).astype(np.int32)
        unc_y = (uncovered_px // self.width).astype(np.int32)
        extra_buckets = [[] for _ in range(len(eids_ordered))]
        for i in range(uncovered_px.size):
          dx = cov_x - unc_x[i]
          dy = cov_y - unc_y[i]
          best_k = int(np.argmin(dx*dx + dy*dy))
          extra_buckets[int(all_own[best_k])].append(int(uncovered_px[i]))
        for i in range(len(eids_ordered)):
          if extra_buckets[i]:
            local_eid = eids_ordered[i]
            out_map[local_eid] = np.unique(np.concatenate([out_map[local_eid], np.array(extra_buckets[i], dtype=np.int32)]))

    #Return statement
    return out_map


  def splitAntimeridianPolygon (self, arg1_polygon):
    """
    @brief Split polygons that wrap across the +-180 degree antimeridian into valid [-180, 180] parts.
    @param arg1_polygon Input Shapely Polygon.
    @return List of Shapely Polygons strictly within [-180, 180] longitude.
    """
    #Convert from parameters
    polygon = arg1_polygon

    #Declare local instance variables
    coords = None
    diffs = None
    east_clip = box(-180.0, -90.0, 180.0, 90.0)
    parts_array = []

    if polygon is None or polygon.is_empty:
      return parts_array

    coords = np.asarray(polygon.exterior.coords, dtype=np.float64)
    if coords.shape[0] < 3:
      return parts_array

    if coords[:, 0].min() >= -180.001 and coords[:, 0].max() <= 180.001:
      diffs = np.abs(np.diff(coords[:, 0]))
      if diffs.max() < 180.0:
        return [polygon]

    try:
      unwrapped_ext = coords.copy()
      unwrapped_ext[:, 0] = np.where(unwrapped_ext[:, 0] < 0.0, unwrapped_ext[:, 0] + 360.0, unwrapped_ext[:, 0])
      unwrapped_holes = []
      for i in range(len(polygon.interiors)):
        local_h = np.asarray(polygon.interiors[i].coords, dtype=np.float64).copy()
        local_h[:, 0] = np.where(local_h[:, 0] < 0.0, local_h[:, 0] + 360.0, local_h[:, 0])
        unwrapped_holes.append(local_h)
      poly_360 = Polygon(unwrapped_ext, unwrapped_holes).buffer(0)
      east_half = poly_360.intersection(box(0.0, -90.0, 180.0, 90.0))
      west_half_360 = poly_360.intersection(box(180.0, -90.0, 360.0, 90.0))
      parts_array.extend(self.extractPolygons(east_half))
      west_polys = self.extractPolygons(west_half_360)
      for i in range(len(west_polys)):
        local_wp = west_polys[i]
        local_ext = np.asarray(local_wp.exterior.coords, dtype=np.float64).copy()
        local_ext[:, 0] = local_ext[:, 0] - 360.0
        local_int = []
        for x in range(len(local_wp.interiors)):
          local_ih = np.asarray(local_wp.interiors[x].coords, dtype=np.float64).copy()
          local_ih[:, 0] = local_ih[:, 0] - 360.0
          local_int.append(local_ih)
        parts_array.extend(self.extractPolygons(Polygon(local_ext, local_int)))
    except Exception:
      parts_array.extend(self.extractPolygons(polygon.intersection(east_clip)))

    #Return statement
    return parts_array if parts_array else [polygon]
