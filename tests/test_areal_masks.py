"""@brief Comprehensive verification suite for the Global Collaboratory WGS84 Equirectangular areal masks."""

import os
import sys
import numpy as np
import orjson
from PIL import Image


class ArealMaskTestSuite:
  """@brief Validates provinces.png, country_masks.json, subadmin_masks.json, city_masks.json and table_masks.json."""

  def __init__ (self, arg1_root_dir=None):
    """
    @brief Initialise ArealMaskTestSuite with repository root path.
    @param arg1_root_dir Optional repository root directory path.
    """
    #Convert from parameters
    root_dir = arg1_root_dir

    #Declare local instance variables
    self.out_dir = ""
    self.root_dir = os.path.abspath(root_dir) if root_dir else os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    self.out_dir = os.path.join(self.root_dir, "output", "areal_masks")


  def packRgbCodes (self, arg1_rgb_triplets_list):
    """
    @brief Convert a list of [R, G, B] triplets into a sorted set of 24-bit packed integer codes.
    @param arg1_rgb_triplets_list List of [R, G, B] integer triplets.
    @return Python set of packed 24-bit integer colourcodes.
    """
    #Convert from parameters
    rgb_triplets_list = arg1_rgb_triplets_list if isinstance(arg1_rgb_triplets_list, list) else []

    #Declare local instance variables
    packed_set = set()

    for i in range(len(rgb_triplets_list)):
      local_c = rgb_triplets_list[i]
      packed_set.add((int(local_c[0]) << 16) | (int(local_c[1]) << 8) | int(local_c[2]))

    #Return statement
    return packed_set


  def runAllTests (self):
    """
    @brief Execute all raster, subadministrative, urban locality, tabular coverage and topological edge-sliver checks.
    @return Boolean True when all assertions succeed.
    """
    #Declare local instance variables
    all_referenced_codes = set()
    arr = None
    city_masks = {}
    country_masks = {}
    harm_dir = os.path.join(self.root_dir, "output", "json", "sectoral_harmonised")
    img = None
    packed_grid = None
    png_path = os.path.join(self.out_dir, "provinces.png")
    present_codes = set()
    raw_dir = os.path.join(self.root_dir, "output", "json", "raw_tables")
    subadmin_masks = {}
    table_masks = {}

    assert os.path.exists(self.out_dir), f"Missing output directory: {self.out_dir}"
    assert os.path.exists(png_path), f"Missing raster: {png_path}"

    img = Image.open(png_path)
    assert img.format == "PNG", f"Expected PNG, got {img.format}"
    assert img.size == (4320, 2160), f"Expected (4320, 2160), got {img.size}"
    assert img.mode == "RGB", f"Expected RGB, got {img.mode}"

    arr = np.asarray(img)
    packed_grid = (
      (arr[:, :, 0].astype(np.uint32) << 16)
      | (arr[:, :, 1].astype(np.uint32) << 8)
      | arr[:, :, 2].astype(np.uint32)
    )
    assert int(np.sum(packed_grid[1860:, :])) == 0, "Antarctica (ATA, south of 65S) must be excluded from provinces.png"

    present_codes = set(int(c) for c in np.unique(packed_grid[packed_grid > 0]))
    land_px = int(np.count_nonzero(packed_grid))
    assert land_px > 2500000, f"Expected > 2,5M land pixels, got {land_px}"
    print(f"[PASS] provinces.png verified: 4320x2160 RGB PNG, {len(present_codes)} province colourcodes, {land_px} land pixels, ATA excluded.")

    country_masks = orjson.loads(open(os.path.join(self.out_dir, "country_masks.json"), "rb").read())
    subadmin_masks = orjson.loads(open(os.path.join(self.out_dir, "subadmin_masks.json"), "rb").read())
    city_masks = orjson.loads(open(os.path.join(self.out_dir, "city_masks.json"), "rb").read())
    table_masks = orjson.loads(open(os.path.join(self.out_dir, "table_masks.json"), "rb").read())

    assert len(country_masks) > 200, f"Expected > 200 countries, got {len(country_masks)}"
    assert len(subadmin_masks) >= 380, f"Expected >= 380 subadmin masks, got {len(subadmin_masks)}"
    assert len(city_masks) >= 80, f"Expected >= 80 city masks, got {len(city_masks)}"

    for local_name, local_dict in (("country_masks.json", country_masks), ("subadmin_masks.json", subadmin_masks)):
      for local_k, local_rgbs in local_dict.items():
        assert isinstance(local_rgbs, list) and len(local_rgbs) > 0, f"Empty RGB list in {local_name}:{local_k}"
        for x in range(len(local_rgbs)):
          c_trip = local_rgbs[x]
          assert len(c_trip) == 3, f"Malformed RGB triplet in {local_name}:{local_k}"
          c_int = (int(c_trip[0]) << 16) | (int(c_trip[1]) << 8) | int(c_trip[2])
          assert c_int in present_codes, f"RGB {c_trip} in {local_name}:{local_k} missing on provinces.png"
          all_referenced_codes.add(c_int)

    assert present_codes == all_referenced_codes, "Orphan RGB colourcodes detected on provinces.png"
    print(f"[PASS] Bijective RGB colourcode integrity verified across {len(country_masks)} countries and {len(subadmin_masks)} subadmin divisions.")

    for local_ck, coords in city_masks.items():
      assert isinstance(coords, list) and len(coords) == 2, f"Malformed city coords for {local_ck}"
      assert -180.0 <= float(coords[0]) <= 180.0 and -90.0 <= float(coords[1]) <= 90.0, f"Out-of-bounds coords for {local_ck}"
    print(f"[PASS] city_masks.json verified: {len(city_masks)} WGS84 [lng, lat] urban coordinates.")

    for local_tk, local_spec in table_masks.items():
      targets = local_spec if isinstance(local_spec, list) else [local_spec]
      assert len(targets) > 0, f"Empty target for {local_tk}"
      for x in range(len(targets)):
        t_str = str(targets[x])
        if t_str.startswith("country:"):
          assert t_str[8:] in country_masks, f"Unresolved country target {t_str} for {local_tk}"
        elif t_str.startswith("subadmin:"):
          assert t_str[9:] in subadmin_masks, f"Unresolved subadmin target {t_str} for {local_tk}"
        elif t_str.startswith("city:"):
          assert t_str[5:] in city_masks, f"Unresolved city target {t_str} for {local_tk}"
        else:
          raise AssertionError(f"Invalid target prefix '{t_str}' for {local_tk}")

    raw_files = sorted(f for f in os.listdir(raw_dir) if f.endswith(".json"))
    harm_files = sorted(f for f in os.listdir(harm_dir) if f.endswith(".json"))
    assert len(raw_files) == 98 and len(harm_files) == 98, "Expected 98 raw_tables and 98 sectoral_harmonised JSON files"
    for i in range(len(raw_files)):
      rf = raw_files[i]
      stem = os.path.splitext(rf)[0]
      assert rf in table_masks and stem in table_masks, f"Missing dataset {rf} in table_masks.json"
      assert f"raw_tables/{stem}" in table_masks and f"sectoral_harmonised/{stem}" in table_masks

    # Verify critical historical, Indian, subadministrative and urban mappings
    assert table_masks["India 1900.json"] == "country:british_india_all"
    assert table_masks["India 2000.json"] == "country:india"
    assert table_masks["Bihar 1900.json"] == "subadmin:british_india.bihar_and_chota_nagpur"
    assert table_masks["Bihar and Johore 2000.json"] == "subadmin:india.bihar_and_jharkhand"
    assert table_masks["Deccan 1800.json"] == "subadmin:company_raj.deccan"
    assert table_masks["Deccan 1800.locality:poona"] == "subadmin:company_raj.poona"
    assert table_masks["Deccan 1900.json"] == "subadmin:british_india.deccan"
    assert table_masks["Goa 1800.json"] == "subadmin:portuguese_goa"
    assert table_masks["Goa 1800.region:old_conquests"] == "subadmin:portuguese_goa.old_conquests"
    assert table_masks["Goa 1800.region:new_conquests"] == "subadmin:portuguese_goa.new_conquests"
    assert table_masks["Goa 1800.locality:bardez"] == "subadmin:portuguese_goa.bardez"
    assert table_masks["England 1800.json"] == "subadmin:england.shf_and_ynr"
    assert table_masks["England 1851.json"] == "subadmin:england"
    assert table_masks["UK1901-full.json"] == "country:uk_1901_gb_ibs"
    assert table_masks["UK1901-full.region:ibs"] == "subadmin:isle_of_man_and_channel_islands"
    assert table_masks["Venice1500 - DJ - Oct2020.json"] == "city:venice"
    assert table_masks["Venice_1785_(AC-December2011)_guilds.json"] == "country:venice_1800"
    assert table_masks["Italy_1936_(AC-December2011)_kho.json"] == ["country:italy_1936", "country:libya"]
    assert table_masks["Russia1500 - DJ - Oct2020.json"] == "subadmin:russia_1500.novgorod_land"
    assert table_masks["Russia1650 - DJ - Oct2020.json"] == "subadmin:russia_1650.european_uezds"
    assert table_masks["Russia1800 - DJ - Oct2020.region:moscow"] == "subadmin:russia_1800.moscow"
    assert table_masks["Russia1650 - DJ - Oct2020.region:moscow"] == "subadmin:russia_1650.moscow"
    print(f"[PASS] table_masks.json verified: {len(table_masks)} dataset and sub-table series keys resolved.")

    # Verify exact partition conservation (zero coastal/frontier stray edge slivers between parent and children)
    self.verifyExactPartitionUnion(
      country_masks["india"],
      [subadmin_masks[k] for k in subadmin_masks if k.startswith("india.") and k != "india.bihar_and_jharkhand"],
      "Modern India states -> india"
    )
    self.verifyExactPartitionUnion(
      country_masks["british_india_ex_burma"],
      [
        subadmin_masks[k] for k in subadmin_masks
        if (k.startswith("british_india.") and k not in ("british_india.bihar_and_chota_nagpur", "british_india.deccan", "british_india.belgaum", "british_india.dharwar", "british_india.poona"))
        or k.startswith("british_india_princely.")
      ],
      "British India provinces + Princely States -> british_india_ex_burma"
    )
    self.verifyExactPartitionUnion(
      subadmin_masks["portuguese_goa"],
      [subadmin_masks["portuguese_goa.old_conquests"], subadmin_masks["portuguese_goa.new_conquests"]],
      "Portuguese Goa Old + New Conquests -> portuguese_goa"
    )
    self.verifyExactPartitionUnion(
      country_masks["indonesia"],
      [subadmin_masks["java_and_madura"]] + [subadmin_masks[k] for k in subadmin_masks if k.startswith("indonesia_1800.")],
      "Java & Madura + 21 Outer Islands Residencies -> indonesia"
    )
    self.verifyExactPartitionUnion(
      country_masks["japan_1800"],
      [subadmin_masks[k] for k in subadmin_masks if k.startswith("japan_1800.")],
      "14 Tokugawa Regions -> japan_1800"
    )
    self.verifyExactPartitionUnion(
      country_masks["uk_1901_gb_ibs"],
      [subadmin_masks["england"], subadmin_masks["scotland"], subadmin_masks["wales"], subadmin_masks["isle_of_man_and_channel_islands"]],
      "ENG + SCT + WAL + IBS -> uk_1901_gb_ibs"
    )
    self.verifyExactPartitionUnion(
      country_masks["russia_1900"],
      [subadmin_masks["russian_empire.european_russia"], subadmin_masks["russian_empire.siberia"]],
      "European Russia + Siberia -> russia_1900"
    )
    print("[PASS] Exact topological partition conservation verified (0 coastal shortfall or border slivers).")

    #Return statement
    return True


  def verifyExactPartitionUnion (self, arg1_parent_rgbs, arg2_children_rgb_lists, arg3_label):
    """
    @brief Assert that the union of child RGB colourcode sets equals the parent RGB colourcode set with zero symmetric difference.
    @param arg1_parent_rgbs Parent [R, G, B] list.
    @param arg2_children_rgb_lists List of child [R, G, B] lists.
    @param arg3_label Human-readable partition label for error diagnostics.
    """
    #Convert from parameters
    parent_rgbs = arg1_parent_rgbs
    children_rgb_lists = arg2_children_rgb_lists if isinstance(arg2_children_rgb_lists, list) else []
    label = str(arg3_label or "partition")

    #Declare local instance variables
    child_union = set()
    parent_set = self.packRgbCodes(parent_rgbs)

    for i in range(len(children_rgb_lists)):
      child_union |= self.packRgbCodes(children_rgb_lists[i])

    diff_set = parent_set ^ child_union
    assert len(diff_set) == 0, f"Partition mismatch ({len(diff_set)} stray colourcodes) in {label}"


if __name__ == "__main__":
  suite = ArealMaskTestSuite()
  if not suite.runAllTests():
    sys.exit(1)
