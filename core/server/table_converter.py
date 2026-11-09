"""Table Converter Module.

Harmonises KNAW Global Collaboratory spreadsheets into flat JSON maps.
Produces both raw tabular JSON and sectorally harmonised JSON datasets.
"""

import json
import os
from pathlib import Path
import re
import openpyxl


def a_load_mapping_config (arg1_config_path):
  """
  Loads the sectoral mapping configuration file.

  @param {str} arg1_config_path - Absolute or relative path to configuration JSON.
  @return {dict} Parsed configuration dictionary containing categories and mappings.
  """
  #Convert from parameters
  let_config_path = arg1_config_path

  #Declare local instance variables
  let_config = {}

  #Guard clauses
  if not os.path.exists(let_config_path):
    print(f"Error: Config file not found at {let_config_path}")
    return {}

  #Function body
  with open(let_config_path, "r", encoding="utf-8") as file_stream:
    let_config = json.load(file_stream)

  #Return statement
  return let_config


def b_discover_tables (arg1_data_dir):
  """
  Discovers all valid Excel spreadsheets within the data directory.

  Excludes temporary backup files and intermediate calculation sheets.

  @param {str} arg1_data_dir - Root directory containing raw country datasets.
  @return {list} List of discovered xlsx file paths.
  """
  #Convert from parameters
  let_data_dir = arg1_data_dir

  #Declare local instance variables
  let_discovered = []
  let_full_path = ""

  #Function body
  for root_dir, _, file_names in os.walk(let_data_dir):
    if "Database.calculations" in root_dir:
      continue
    for file_name in file_names:
      if file_name.endswith(".xlsx") and not file_name.startswith("~$"):
        let_full_path = os.path.join(root_dir, file_name)
        let_discovered.append(let_full_path)

  let_discovered.sort()

  #Return statement
  return let_discovered


def c_parse_table (arg1_file_path):
  """
  Parses a KNAW Excel spreadsheet into memory.

  Extracts the Data entry sheet into a structured list of column definitions
  and row records indexed by Id_pop.

  @param {str} arg1_file_path - Path to the Excel workbook.
  @return {tuple} (headers, list of row dicts) or (None, None) if not a standard data table.
  """
  #Convert from parameters
  let_file_path = arg1_file_path

  #Declare local instance variables
  let_cell_val = None
  let_col_name = ""
  let_country = None
  let_first_row = None
  let_headers = []
  let_id_key = ""
  let_id_pop = None
  let_records = []
  let_row_dict = {}
  let_sheet = None
  let_total = None
  let_workbook = None

  #Function body
  try:
    let_workbook = openpyxl.load_workbook(let_file_path, read_only=True, data_only=True)
    if "Data entry" not in let_workbook.sheetnames:
      let_workbook.close()
      return None, None

    let_sheet = let_workbook["Data entry"]
    let_first_row = next(let_sheet.iter_rows(max_row=1, values_only=True))

    for cell_value in let_first_row:
      if cell_value is not None and str(cell_value).strip():
        let_col_name = str(cell_value).strip().strip("[]")
        let_headers.append(let_col_name)

    #Restrict to standard 40 KNAW columns
    let_headers = let_headers[:40]

    for row_cells in let_sheet.iter_rows(min_row=4, values_only=True):
      let_country = row_cells[10] if len(row_cells) > 10 else None
      let_total = row_cells[11] if len(row_cells) > 11 else None

      #Terminate at empty sentinel rows
      if let_country is None and let_total is None:
        break

      let_id_pop = row_cells[1] if len(row_cells) > 1 else None
      if let_id_pop is None or str(let_id_pop).strip() == "":
        continue

      if isinstance(let_id_pop, float) and let_id_pop.is_integer():
        let_id_key = str(int(let_id_pop)).strip()
      else:
        let_id_key = str(let_id_pop).strip()

      let_row_dict = {}
      for i, col_name in enumerate(let_headers):
        let_cell_val = row_cells[i] if len(row_cells) > i else None
        if isinstance(let_cell_val, float) and let_cell_val.is_integer():
          let_cell_val = int(let_cell_val)
        let_row_dict[col_name] = let_cell_val

      let_records.append((let_id_key, let_row_dict))

    let_workbook.close()
  except Exception as error:
    print(f"Warning: Failed to parse {let_file_path}: {error}")
    return None, None

  #Return statement
  return let_headers, let_records


def d_harmonise_branch (
  arg1_branch,
  arg2_type_activity,
  arg3_labour_rel,
  arg4_config,
  arg5_occup=None,
  arg6_options=None
):
  """
  Maps a specific record across the 6-stage KNAW sectoral resolution cascade.

  Categories: agriculture, manufacturing, services, informal labour, not in work.
  Stages:
    1. Branch string lookup (branch_map).
    2. Non-working Labour_rel_01 codes (1, 2, 3, 203, 108, 10305).
    3. Occupation string lookup (occup_map and branch_map).
    4. Position and Remark string lookup (position_map).
    5. HISCO code lookup (Occup_HISCO and Branch_HISCO in hisco_map).
    6. Dataset-specific census weights (dataset_sector_weights) and Labour_rel_01 fallback (labour_rel_map).

  @param {str} arg1_branch - Raw branch string.
  @param {str} arg2_type_activity - Type of activity ('P', 'L', or 'E').
  @param {any} arg3_labour_rel - Primary labour relation identifier.
  @param {dict} arg4_config - Sectoral mapping configuration dictionary.
  @param {str} [arg5_occup=None] - Optional occupation descriptor.
  @param {dict} [arg6_options=None] - Optional dictionary with row_dict, dataset_key, and return_weights.
  @return {str|dict|None} Harmonised sectoral category name (or weight dict when return_weights=True), or None.
  """
  #Convert from parameters
  let_branch = arg1_branch
  let_type_activity = str(arg2_type_activity or "").strip().upper()
  let_labour_rel = str(arg3_labour_rel or "").strip()
  let_config = arg4_config if isinstance(arg4_config, dict) else {}
  let_occup = arg5_occup
  options = arg6_options if isinstance(arg6_options, dict) else {}

  #Declare local instance variables
  let_branch_hisco = ""
  let_branch_map = let_config.get("branch_map", {})
  let_branch_norm = ""
  let_branch_str = str(let_branch).strip() if let_branch is not None else ""
  let_clean_stem = ""
  let_dataset_key = str(options.get("dataset_key") or "").strip()
  let_dataset_weights = let_config.get("dataset_sector_weights", {})
  let_hisco_candidates = []
  let_hisco_map = let_config.get("hisco_map", {})
  let_hisco_prefix = 0
  let_labour_rel_map = let_config.get("labour_rel_map", {})
  let_mapped = None
  let_occup_hisco = ""
  let_occup_lower = ""
  let_occup_map = let_config.get("occup_map", {})
  let_occup_norm = ""
  let_occup_str = str(let_occup).strip() if let_occup is not None else ""
  let_position_map = let_config.get("position_map", {})
  let_position_norm = ""
  let_position_str = ""
  let_remark_lower = ""
  let_return_weights = bool(options.get("return_weights", False))
  let_row_dict = options.get("row_dict") if isinstance(options.get("row_dict"), dict) else {}
  let_weights_result = None

  #Guard clauses
  if let_type_activity.startswith("P"):
    return {"not in work": 1.0} if let_return_weights else "not in work"

  #Function body
  let_branch_norm = let_branch_str.replace("\u03a4", "T").replace("\u0395", "E")
  let_occup_norm = let_occup_str.replace("\u03a4", "T").replace("\u0395", "E")
  let_position_str = str(let_row_dict.get("Position") or options.get("position") or "").strip()
  let_position_norm = let_position_str.replace("\u03a4", "T").replace("\u0395", "E")
  let_remark_lower = str(let_row_dict.get("Remark") or options.get("remark") or "").strip().lower()
  let_occup_hisco = str(let_row_dict.get("Occup_HISCO") or options.get("occup_hisco") or "").strip()
  let_branch_hisco = str(let_row_dict.get("Branch_HISCO") or options.get("branch_hisco") or "").strip()

  #Stage 1: Check Branch dictionary first
  if let_branch_str and let_branch_str not in ("NA", "None", "-1"):
    for local_b_candidate in (let_branch_str, let_branch_norm):
      if local_b_candidate in let_branch_map:
        let_mapped = let_branch_map[local_b_candidate]
        if let_mapped != "unclassified":
          return {let_mapped: 1.0} if let_return_weights else let_mapped

  #Stage 2: Check explicit non-working Labour_rel_01 codes
  #1 = Cannot work / not expected to work, 2 = Affluent, 3 = Unemployed, 203/108/10305 = Retired/Student/Inactive
  if let_labour_rel in ("1", "2", "3", "203", "108", "10305"):
    if let_position_str == "People who beg":
      return {"informal labour": 1.0} if let_return_weights else "informal labour"
    return {"not in work": 1.0} if let_return_weights else "not in work"

  #Stage 3: Check Occup dictionary (occup_map and branch_map)
  if let_occup_str and let_occup_str not in ("NA", "None", "-1"):
    for local_o_candidate in (let_occup_str, let_occup_norm):
      if local_o_candidate in let_occup_map:
        let_mapped = let_occup_map[local_o_candidate]
        if let_mapped != "unclassified":
          return {let_mapped: 1.0} if let_return_weights else let_mapped
      if local_o_candidate in let_branch_map:
        let_mapped = let_branch_map[local_o_candidate]
        if let_mapped != "unclassified":
          return {let_mapped: 1.0} if let_return_weights else let_mapped

    let_occup_lower = let_occup_norm.lower()
    if any(
      local_kw in let_occup_lower
      for local_kw in ("old to work", "unemployed", "too young", "not working", "inmates", "pensioner", "rentier")
    ):
      return {"not in work": 1.0} if let_return_weights else "not in work"

  #Stage 4: Check Position and Remark
  if let_position_str and let_position_str not in ("NA", "None", "-1"):
    for local_p_candidate in (let_position_str, let_position_norm):
      if local_p_candidate in let_position_map:
        let_mapped = let_position_map[local_p_candidate]
        if let_mapped != "unclassified":
          return {let_mapped: 1.0} if let_return_weights else let_mapped

  if let_remark_lower:
    if (
      "without occupation" in let_remark_lower
      or "without profession" in let_remark_lower
      or "dependents on their families" in let_remark_lower
      or (let_labour_rel == "5" and "household activities" in let_remark_lower)
    ):
      return {"not in work": 1.0} if let_return_weights else "not in work"
    if "beggar" in let_remark_lower:
      return {"informal labour": 1.0} if let_return_weights else "informal labour"

  #Stage 5: Check Occup_HISCO (more granular) then Branch_HISCO
  let_hisco_candidates = [let_occup_hisco, let_branch_hisco]
  for i in range(len(let_hisco_candidates)):
    local_hisco = let_hisco_candidates[i]
    if not local_hisco or local_hisco in ("NA", "None", "-1"):
      continue
    if local_hisco in let_hisco_map:
      let_mapped = let_hisco_map[local_hisco]
      return {let_mapped: 1.0} if let_return_weights else let_mapped
    if len(local_hisco) >= 3 and local_hisco[:3] in let_hisco_map:
      let_mapped = let_hisco_map[local_hisco[:3]]
      return {let_mapped: 1.0} if let_return_weights else let_mapped
    if len(local_hisco) >= 2 and local_hisco[:2].isdigit():
      let_hisco_prefix = int(local_hisco[:2])
      if 0 <= let_hisco_prefix <= 59:
        let_mapped = "services"
      elif 60 <= let_hisco_prefix <= 69:
        let_mapped = "agriculture"
      elif 70 <= let_hisco_prefix <= 97:
        let_mapped = "manufacturing"
      elif let_hisco_prefix == 98:
        let_mapped = "services"
      else:
        let_mapped = "informal labour"
      return {let_mapped: 1.0} if let_return_weights else let_mapped
    if local_hisco[:1] in let_hisco_map:
      let_mapped = let_hisco_map[local_hisco[:1]]
      return {let_mapped: 1.0} if let_return_weights else let_mapped

  #Stage 6: Dataset-specific census weights and Labour_rel_01 fallback
  let_clean_stem = let_dataset_key.replace(" ", "").replace("_", "")
  for local_ds_key, local_ds_table in let_dataset_weights.items():
    if let_clean_stem.startswith(local_ds_key):
      if let_labour_rel in local_ds_table:
        let_weights_result = local_ds_table[let_labour_rel]
        break
      elif "-1" in local_ds_table and let_labour_rel in ("", "NA", "None", "-1"):
        let_weights_result = local_ds_table["-1"]
        break

  if let_weights_result is None and let_labour_rel in let_labour_rel_map:
    let_mapped = let_labour_rel_map[let_labour_rel]
    if let_mapped != "unclassified":
      let_weights_result = {let_mapped: 1.0}

  #Return statement
  if let_weights_result is not None:
    if let_return_weights:
      return let_weights_result
    return max(let_weights_result.items(), key=lambda item: item[1])[0]
  return None


def e_write_raw_json (arg1_records, arg2_output_path):
  """
  Writes tabular records as a flat JSON map keyed by Id_pop into the target path.

  @param {list} arg1_records - List of (id_key, row_dict) tuples.
  @param {str} arg2_output_path - Destination JSON file path.
  @return {bool} True on success, False otherwise.
  """
  #Convert from parameters
  let_records = arg1_records
  let_output_path = arg2_output_path

  #Declare local instance variables
  let_flat_map = {}

  #Function body
  for id_key, row_dict in let_records:
    let_flat_map[id_key] = row_dict

  os.makedirs(os.path.dirname(let_output_path), exist_ok=True)
  with open(let_output_path, "w", encoding="utf-8") as file_stream:
    json.dump(let_flat_map, file_stream, indent=2, ensure_ascii=False)

  #Return statement
  return True


def f_write_harmonised_json (arg1_records, arg2_output_path, arg3_config, arg4_options=None):
  """
  Writes sectorally harmonised records as a squished flat JSON map into the target path.

  Format: {"<sector>_<year>": number, ...}

  @param {list} arg1_records - List of (id_key, row_dict) tuples.
  @param {str} arg2_output_path - Destination JSON file path.
  @param {dict} arg3_config - Sectoral mapping configuration dictionary.
  @param {dict} [arg4_options=None] - Optional dictionary containing dataset_key.
  @return {bool} True on success, False otherwise.
  """
  #Convert from parameters
  let_records = arg1_records
  let_output_path = arg2_output_path
  let_config = arg3_config if isinstance(arg3_config, dict) else {}
  options = arg4_options if isinstance(arg4_options, dict) else {}

  #Declare local instance variables
  let_all_empty_fields = False
  let_branch = ""
  let_composite_key = ""
  let_dataset_key = str(options.get("dataset_key") or Path(let_output_path).stem).strip()
  let_flat_map = {}
  let_harmonised_totals = {}
  let_key = ""
  let_labour_rel = None
  let_match = None
  let_occup = None
  let_raw_val = 0
  let_redundant_ids = set(let_config.get("redundant_id_pops", {}).get(let_dataset_key, []))
  let_sector_key = ""
  let_sector_weights = None
  let_total = 0
  let_type_act = ""
  let_val = 0
  let_year = ""
  let_year_start = ""
  let_year_str = ""

  #Function body
  for id_key, row_dict in let_records:
    if str(id_key).strip() in let_redundant_ids:
      continue

    let_type_act = str(row_dict.get("Type_activity") or "").strip().upper()
    if let_type_act not in ("L", "E"):
      continue

    let_branch = str(row_dict.get("Branch") or "").strip()
    if let_branch in ("Total population", "Working population"):
      continue

    let_occup = row_dict.get("Occup")
    if str(let_occup or "").strip() == "Double counted professions":
      continue

    let_total = row_dict.get("Total")
    if let_total is None or not isinstance(let_total, (int, float)) or let_total <= 0:
      continue

    #Skip unallocated total-population header rows where all classification and remark columns are empty/NA
    let_all_empty_fields = all(
      str(row_dict.get(local_col) or "").strip() in ("", "NA", "None", "-1")
      for local_col in ("Branch", "Occup", "Position", "Branch_HISCO", "Occup_HISCO", "Labour_rel_01", "Remark")
    )
    if let_all_empty_fields:
      continue

    let_labour_rel = row_dict.get("Labour_rel_01")
    let_sector_weights = d_harmonise_branch(
      let_branch,
      let_type_act,
      let_labour_rel,
      let_config,
      let_occup,
      {
        "dataset_key": let_dataset_key,
        "return_weights": True,
        "row_dict": row_dict
      }
    )
    if not let_sector_weights:
      continue

    #Resolve clean 4-digit year string
    let_year = str(row_dict.get("Year") or "").strip()
    let_year_start = str(row_dict.get("Year_start") or "").strip()
    if let_year.isdigit():
      let_year_str = let_year
    elif let_year_start.isdigit():
      let_year_str = let_year_start
    else:
      let_match = re.search(r"\d{4}", let_year)
      let_year_str = let_match.group(0) if let_match else let_year

    for local_sector, local_weight in let_sector_weights.items():
      let_sector_key = local_sector.replace(" ", "_")
      let_composite_key = f"{let_sector_key}_{let_year_str}"
      let_harmonised_totals[let_composite_key] = (
        let_harmonised_totals.get(let_composite_key, 0.0) + float(let_total)*float(local_weight)
      )

  #Format numbers: integer if exact, rounded float otherwise
  for let_key in sorted(let_harmonised_totals.keys()):
    let_raw_val = let_harmonised_totals[let_key]
    if isinstance(let_raw_val, float) and abs(let_raw_val - round(let_raw_val)) < 1e-2:
      let_val = int(round(let_raw_val))
    elif isinstance(let_raw_val, float):
      let_val = int(round(let_raw_val))
    else:
      let_val = int(let_raw_val)
    let_flat_map[let_key] = let_val

  os.makedirs(os.path.dirname(let_output_path), exist_ok=True)
  with open(let_output_path, "w", encoding="utf-8") as file_stream:
    json.dump(let_flat_map, file_stream, indent=2, ensure_ascii=False)

  #Return statement
  return True


def g_run_pipeline (
  arg1_data_dir="data",
  arg2_output_dir="output/json",
  arg3_config_path="common/sectoral_mapping.json",
  arg4_options=None
):
  """
  Executes the complete end-to-end table conversion pipeline.

  @param {str} arg1_data_dir - Input data directory.
  @param {str} arg2_output_dir - Root JSON output directory.
  @param {str} arg3_config_path - Configuration path for sectoral mapping.
  @param {dict} [arg4_options=None] - Optional settings such as force_parse_excel.
  @return {dict} Summary statistics of converted tables.
  """
  #Convert from parameters
  let_data_dir = arg1_data_dir
  let_output_dir = arg2_output_dir
  let_config_path = arg3_config_path
  options = arg4_options if isinstance(arg4_options, dict) else {}

  #Declare local instance variables
  let_config = {}
  let_converted_count = 0
  let_force_excel = bool(options.get("force_parse_excel", False))
  let_harmonised_file_path = ""
  let_harmonised_out_dir = os.path.join(let_output_dir, "sectoral_harmonised")
  let_headers = None
  let_json_filename = ""
  let_raw_file_path = ""
  let_raw_map = {}
  let_raw_out_dir = os.path.join(let_output_dir, "raw_tables")
  let_records = []
  let_skipped_count = 0
  let_stem = ""
  let_table_files = []

  #Function body
  #Step A: Load config
  let_config = a_load_mapping_config(let_config_path)

  #Step B: Discover tables
  let_table_files = b_discover_tables(let_data_dir)
  print(f"Discovered {len(let_table_files)} potential spreadsheet files.")

  #Step C-F: Process each spreadsheet
  for i in range(len(let_table_files)):
    local_table_path = let_table_files[i]
    let_stem = Path(local_table_path).stem
    let_json_filename = f"{let_stem}.json"
    let_raw_file_path = os.path.join(let_raw_out_dir, let_json_filename)
    let_harmonised_file_path = os.path.join(let_harmonised_out_dir, let_json_filename)

    if not let_force_excel and os.path.exists(let_raw_file_path):
      with open(let_raw_file_path, "r", encoding="utf-8") as raw_stream:
        let_raw_map = json.load(raw_stream)
      let_records = list(let_raw_map.items())
    else:
      let_headers, let_records = c_parse_table(local_table_path)
      if let_headers is None or not let_records:
        let_skipped_count += 1
        continue
      #Step E: Write raw JSON
      e_write_raw_json(let_records, let_raw_file_path)

    #Step F: Write harmonised JSON
    f_write_harmonised_json(
      let_records,
      let_harmonised_file_path,
      let_config,
      {"dataset_key": let_stem}
    )

    let_converted_count += 1

  print(f"Pipeline completed: {let_converted_count} files converted, {let_skipped_count} non-standard skipped.")

  #Return statement
  return {
    "converted": let_converted_count,
    "skipped": let_skipped_count
  }


if __name__ == "__main__":
  g_run_pipeline()
