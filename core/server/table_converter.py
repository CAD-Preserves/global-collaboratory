"""Table Converter Module.

Harmonises KNAW Global Collaboratory spreadsheets into flat JSON maps.
Produces both raw tabular JSON and sectorally harmonised JSON datasets.
"""

import json
import os
from pathlib import Path
import sys
import openpyxl


def a_load_mapping_config(arg1_config_path):
  """Loads the sectoral mapping configuration file.

  @param {str} arg1_config_path - Absolute or relative path to configuration JSON.
  @return {dict} Parsed configuration dictionary containing categories and branch mappings.
  """
  # Convert from parameters
  let_config_path = arg1_config_path

  # Guard clause
  if not os.path.exists(let_config_path):
    print(f"Error: Config file not found at {let_config_path}")
    return {}

  # Function body
  with open(let_config_path, "r", encoding="utf-8") as file_stream:
    let_config = json.load(file_stream)

  # Return statement
  return let_config


def b_discover_tables(arg1_data_dir):
  """Discovers all valid Excel spreadsheets within the data directory.

  Excludes temporary backup files and intermediate calculation sheets.

  @param {str} arg1_data_dir - Root directory containing raw country datasets.
  @return {list} List of discovered xlsx file paths.
  """
  # Convert from parameters
  let_data_dir = arg1_data_dir

  # Declare local instance variables
  let_discovered = []

  # Function body
  for root_dir, _, file_names in os.walk(let_data_dir):
    if "Database.calculations" in root_dir:
      continue
    for file_name in file_names:
      if file_name.endswith(".xlsx") and not file_name.startswith("~$"):
        let_full_path = os.path.join(root_dir, file_name)
        let_discovered.append(let_full_path)

  let_discovered.sort()

  # Return statement
  return let_discovered


def c_parse_table(arg1_file_path):
  """Parses a KNAW Excel spreadsheet into memory.

  Extracts the Data entry sheet into a structured list of column definitions
  and row records indexed by Id_pop.

  @param {str} arg1_file_path - Path to the Excel workbook.
  @return {tuple} (headers, list of row dicts) or (None, None) if not a standard data table.
  """
  # Convert from parameters
  let_file_path = arg1_file_path

  # Declare local instance variables
  let_headers = []
  let_records = []

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

    # Restrict to standard 40 KNAW columns
    let_headers = let_headers[:40]

    for row_cells in let_sheet.iter_rows(min_row=4, values_only=True):
      let_country = row_cells[10] if len(row_cells) > 10 else None
      let_total = row_cells[11] if len(row_cells) > 11 else None

      # Terminate at empty sentinel rows
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
      for col_idx, col_name in enumerate(let_headers):
        let_cell_val = row_cells[col_idx] if len(row_cells) > col_idx else None
        if isinstance(let_cell_val, float) and let_cell_val.is_integer():
          let_cell_val = int(let_cell_val)
        let_row_dict[col_name] = let_cell_val

      let_records.append((let_id_key, let_row_dict))

    let_workbook.close()
  except Exception as error:
    print(f"Warning: Failed to parse {let_file_path}: {error}")
    return None, None

  # Return statement
  return let_headers, let_records


def d_harmonise_branch(arg1_branch, arg2_type_activity, arg3_labour_rel, arg4_config, arg5_occup=None):
  """Maps a specific record branch and relation into one of the five harmonised sectors.

  Categories: agriculture, manufacturing, services, informal labour, not in work.

  @param {str} arg1_branch - Raw branch string.
  @param {str} arg2_type_activity - Type of activity (e.g. 'P' for population, 'L' for labour).
  @param {any} arg3_labour_rel - Primary labour relation identifier.
  @param {dict} arg4_config - Sectoral mapping configuration dictionary.
  @param {str} [arg5_occup=None] - Optional occupation descriptor.
  @return {str|None} Harmonised sectoral category name, or None if unclassified.
  """
  # Convert from parameters
  let_branch = arg1_branch
  let_type_activity = str(arg2_type_activity or "").strip().upper()
  let_labour_rel = str(arg3_labour_rel or "").strip()
  let_config = arg4_config
  let_occup = arg5_occup

  # Declare local instance variables
  let_branch_map = let_config.get("branch_map", {})
  let_branch_str = str(let_branch).strip() if let_branch is not None else ""
  let_occup_lower = ""
  let_occup_str = str(let_occup).strip() if let_occup is not None else ""

  # Guard clauses
  if let_type_activity.startswith("P"):
    return "not in work"

  # Function body
  # 1. Check exact branch map dictionary first
  if let_branch_str and let_branch_str not in ("NA", "None"):
    if let_branch_str in let_branch_map:
      let_mapped = let_branch_map[let_branch_str]
      if let_mapped != "unclassified":
        # Return statement
        return let_mapped

  # 2. Check labour relation codes for non-working status
  # 1 = Incapable / not supposed to work, 2 = Affluent, 3 = Unemployed
  if let_labour_rel in ("1", "2", "3"):
    # Return statement
    return "not in work"

  # 3. Check occupation field if branch was uninformative
  if let_occup_str and let_occup_str not in ("NA", "None"):
    if let_occup_str in let_branch_map:
      let_mapped_occup = let_branch_map[let_occup_str]
      if let_mapped_occup != "unclassified":
        # Return statement
        return let_mapped_occup
    let_occup_lower = let_occup_str.lower()
    if any(keyword in let_occup_lower for keyword in ["children", "old to work", "unemployed", "young"]):
      # Return statement
      return "not in work"

  # Return statement
  return None


def e_write_raw_json(arg1_records, arg2_output_path):
  """Writes tabular records as a flat JSON map keyed by Id_pop into the target path.

  @param {list} arg1_records - List of (id_key, row_dict) tuples.
  @param {str} arg2_output_path - Destination JSON file path.
  @return {bool} True on success, False otherwise.
  """
  # Convert from parameters
  let_records = arg1_records
  let_output_path = arg2_output_path

  # Function body
  let_flat_map = {}
  for id_key, row_dict in let_records:
    let_flat_map[id_key] = row_dict

  os.makedirs(os.path.dirname(let_output_path), exist_ok=True)
  with open(let_output_path, "w", encoding="utf-8") as file_stream:
    json.dump(let_flat_map, file_stream, indent=2, ensure_ascii=False)

  # Return statement
  return True


def f_write_harmonised_json(arg1_records, arg2_output_path, arg3_config):
  """Writes sectorally harmonised records as a squished flat JSON map into the target path.

  Format: {"<sector>_<year>": number, ...}

  @param {list} arg1_records - List of (id_key, row_dict) tuples.
  @param {str} arg2_output_path - Destination JSON file path.
  @param {dict} arg3_config - Sectoral mapping configuration dictionary.
  @return {bool} True on success, False otherwise.
  """
  # Convert from parameters
  let_records = arg1_records
  let_output_path = arg2_output_path
  let_config = arg3_config

  # Declare local instance variables
  let_composite_key = ""
  let_flat_map = {}
  let_harmonised_totals = {}
  let_key = ""
  let_raw_val = 0
  let_val = 0

  # Function body
  for _, row_dict in let_records:
    let_type_act = str(row_dict.get("Type_activity") or "").strip().upper()
    if let_type_act not in ("L", "E"):
      continue

    let_branch = str(row_dict.get("Branch") or "").strip()
    if let_branch in ("Total population", "Working population"):
      continue

    let_occup = row_dict.get("Occup")
    let_labour_rel = row_dict.get("Labour_rel_01")
    let_sector = d_harmonise_branch(let_branch, let_type_act, let_labour_rel, let_config, let_occup)
    if not let_sector:
      continue

    let_year = row_dict.get("Year")
    if let_year is None or str(let_year).strip() in ("", "-1", "NA"):
      let_year = row_dict.get("Year_start")
    let_year_str = str(let_year).strip()

    let_total = row_dict.get("Total")
    if let_total is None or not isinstance(let_total, (int, float)) or let_total <= 0:
      continue

    let_sector_key = let_sector.replace(" ", "_")
    let_composite_key = f"{let_sector_key}_{let_year_str}"
    let_harmonised_totals[let_composite_key] = let_harmonised_totals.get(let_composite_key, 0) + let_total

  # Format numbers: integer if exact, rounded float otherwise
  for let_key in sorted(let_harmonised_totals.keys()):
    let_raw_val = let_harmonised_totals[let_key]
    if isinstance(let_raw_val, float) and abs(let_raw_val - round(let_raw_val)) < 1e-4:
      let_val = int(round(let_raw_val))
    elif isinstance(let_raw_val, float):
      let_val = round(let_raw_val, 2)
    else:
      let_val = let_raw_val
    let_flat_map[let_key] = let_val

  os.makedirs(os.path.dirname(let_output_path), exist_ok=True)
  with open(let_output_path, "w", encoding="utf-8") as file_stream:
    json.dump(let_flat_map, file_stream, indent=2, ensure_ascii=False)

  # Return statement
  return True


def g_run_pipeline(arg1_data_dir="data", arg2_output_dir="output/json", arg3_config_path="common/sectoral_mapping.json"):
  """Executes the complete end-to-end table conversion pipeline.

  @param {str} arg1_data_dir - Input data directory.
  @param {str} arg2_output_dir - Root JSON output directory.
  @param {str} arg3_config_path - Configuration path for sectoral mapping.
  @return {dict} Summary statistics of converted tables.
  """
  # Convert from parameters
  let_data_dir = arg1_data_dir
  let_output_dir = arg2_output_dir
  let_config_path = arg3_config_path

  # Declare local instance variables
  let_converted_count = 0
  let_harmonised_out_dir = os.path.join(let_output_dir, "sectoral_harmonised")
  let_raw_out_dir = os.path.join(let_output_dir, "raw_tables")
  let_skipped_count = 0

  # Step A: Load config
  let_config = a_load_mapping_config(let_config_path)

  # Step B: Discover tables
  let_table_files = b_discover_tables(let_data_dir)
  print(f"Discovered {len(let_table_files)} potential spreadsheet files.")

  # Step C-F: Process each spreadsheet
  for table_path in let_table_files:
    let_headers, let_records = c_parse_table(table_path)
    if let_headers is None or not let_records:
      let_skipped_count += 1
      continue

    let_stem = Path(table_path).stem
    let_json_filename = f"{let_stem}.json"

    let_raw_file_path = os.path.join(let_raw_out_dir, let_json_filename)
    let_harmonised_file_path = os.path.join(let_harmonised_out_dir, let_json_filename)

    # Step E: Write raw JSON
    e_write_raw_json(let_records, let_raw_file_path)

    # Step F: Write harmonised JSON
    f_write_harmonised_json(let_records, let_harmonised_file_path, let_config)

    let_converted_count += 1

  print(f"Pipeline completed: {let_converted_count} files converted, {let_skipped_count} non-standard skipped.")

  # Return statement
  return {
    "converted": let_converted_count,
    "skipped": let_skipped_count
  }


if __name__ == "__main__":
  g_run_pipeline()
