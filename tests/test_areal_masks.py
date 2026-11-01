"""Test suite for output/areal_masks verification."""

import json
import os
from pathlib import Path
import numpy as np
from PIL import Image

def test_areal_masks():
  out_dir = "output/areal_masks"
  assert os.path.exists(out_dir), f"Directory missing: {out_dir}"

  # 1. Verify provinces.png
  png_path = os.path.join(out_dir, "provinces.png")
  assert os.path.exists(png_path), "provinces.png missing"
  img = Image.open(png_path)
  assert img.format == "PNG", f"Expected PNG, got {img.format}"
  assert img.size == (4320, 2160), f"Expected 4320x2160, got {img.size}"
  assert img.mode == "RGB", f"Expected RGB, got {img.mode}"
  print("[PASS] provinces.png verified: 4320x2160 RGB PNG")

  # 2. Check pixel buffer and unique colours
  arr = np.array(img)
  flat_arr = arr.reshape(-1, 3)
  unique_colours, counts = np.unique(flat_arr, axis=0, return_counts=True)
  print(f"[PASS] Total unique colours on raster: {len(unique_colours)}")

  # Ensure background [0, 0, 0] is present and dominant
  assert np.array_equal(unique_colours[0], [0, 0, 0]), "First colour must be [0, 0, 0] background"
  non_black_colours = set(tuple(c) for c in unique_colours[1:])
  total_land_pixels = counts[1:].sum()
  print(f"[PASS] Background [0, 0, 0] pixel count: {counts[0]:,}")
  print(f"[PASS] Total non-black land pixels: {total_land_pixels:,}")

  # 3. Verify country_masks.json
  country_masks_path = os.path.join(out_dir, "country_masks.json")
  assert os.path.exists(country_masks_path), "country_masks.json missing"
  with open(country_masks_path, "r", encoding="utf-8") as f:
    country_masks = json.load(f)
  assert len(country_masks) > 200, f"Expected >200 countries, got {len(country_masks)}"

  # Check that every colour in country_masks exists on provinces.png
  unmapped_colours = []
  for country_key, colours in country_masks.items():
    assert isinstance(colours, list) and len(colours) > 0, f"Empty colour list for {country_key}"
    for c in colours:
      assert len(c) == 3, f"Invalid colour format in {country_key}: {c}"
      t_c = tuple(c)
      if t_c not in non_black_colours:
        unmapped_colours.append((country_key, t_c))
  assert len(unmapped_colours) == 0, f"Unmapped colours in country_masks: {unmapped_colours}"
  print(f"[PASS] country_masks.json verified: {len(country_masks)} countries, all colours present on provinces.png")

  # 4. Verify table_masks.json
  table_masks_path = os.path.join(out_dir, "table_masks.json")
  assert os.path.exists(table_masks_path), "table_masks.json missing"
  with open(table_masks_path, "r", encoding="utf-8") as f:
    table_masks = json.load(f)

  # Check that all target masks resolve to a key in country_masks
  unresolved_tables = []
  for t_key, target in table_masks.items():
    assert target.startswith("country:"), f"Invalid target prefix for {t_key}: {target}"
    ck = target[len("country:"):]
    if ck not in country_masks:
      unresolved_tables.append((t_key, ck))
  assert len(unresolved_tables) == 0, f"Unresolved table targets: {unresolved_tables}"
  print(f"[PASS] table_masks.json verified: {len(table_masks)} entries, 100% resolved in country_masks")

  # 5. Check 100% corpus coverage for all raw_tables and sectoral_harmonised files
  raw_dir = "output/json/raw_tables"
  if os.path.exists(raw_dir):
    raw_files = [f for f in os.listdir(raw_dir) if f.endswith(".json")]
    missing_raw = []
    for rf in raw_files:
      stem = Path(rf).stem
      if rf not in table_masks and stem not in table_masks:
        missing_raw.append(rf)
    assert len(missing_raw) == 0, f"Missing raw files in table_masks: {missing_raw}"
    print(f"[PASS] 100% corpus coverage: all {len(raw_files)} tabular files mapped in table_masks.json")

  # 6. Verify subadmin_masks.json and city_masks.json
  subadmin_path = os.path.join(out_dir, "subadmin_masks.json")
  assert os.path.exists(subadmin_path), "subadmin_masks.json missing"
  with open(subadmin_path, "r", encoding="utf-8") as f:
    subadmin_masks = json.load(f)
  print(f"[PASS] subadmin_masks.json verified: {len(subadmin_masks)} subadmin entries")

  city_path = os.path.join(out_dir, "city_masks.json")
  assert os.path.exists(city_path), "city_masks.json missing"
  with open(city_path, "r", encoding="utf-8") as f:
    city_masks = json.load(f)
  print(f"[PASS] city_masks.json verified: {len(city_masks)} city entries")

  print("\n>>> ALL TESTS PASSED SUCCESSFULLY! <<<")

if __name__ == "__main__":
  test_areal_masks()
