"""@brief Configuration and localisation loader for the Global Collaboratory areal mask pipeline."""

import os
import sys
import pyjson5


class ConfigLoader:
  """@brief Loads JSON/JSON5 configuration files from /common/ and localised strings from /localisation/."""

  def __init__ (self, arg1_root_dir=None, arg2_options=None):
    """
    @brief Initialise ConfigLoader with workspace paths and locale settings.
    @param arg1_root_dir Root repository path (defaults to two levels above /core/server/).
    @param arg2_options Optional dictionary overriding config_subdir or locale ('en_gb', 'fr', 'de').
    """
    #Convert from parameters
    root_dir = arg1_root_dir
    options = arg2_options if isinstance(arg2_options, dict) else {}

    #Initialise options
    if "config_subdir" not in options:
      options["config_subdir"] = os.path.join("common", "areal_masks")
    if "locale" not in options or not options["locale"]:
      options["locale"] = "en_gb"

    #Declare local instance variables
    default_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    self.areal_config_obj = {}
    self.locale = str(options["locale"])
    self.localisation_obj = {}
    self.root_dir = os.path.abspath(root_dir) if root_dir else default_root

    self.loadAllConfigs(options["config_subdir"])


  def formatEuropeanNumber (self, arg1_value, arg2_options=None):
    """
    @brief Format a numeric value using European decimals (58,88) and semantic suffixes (k, M, B, T).
    @param arg1_value Integer or float value to format.
    @param arg2_options Optional dictionary with decimals (default 2) and use_abbreviation (default True).
    @return Formatted string in European decimal notation.
    """
    #Convert from parameters
    value = arg1_value
    options = arg2_options if isinstance(arg2_options, dict) else {}

    #Initialise options
    if "decimals" not in options:
      options["decimals"] = 2
    if "use_abbreviation" not in options:
      options["use_abbreviation"] = True

    #Declare local instance variables
    abs_val = 0.0
    decimals = int(options["decimals"])
    formatted_str = ""
    scaled_val = 0.0
    suffix_array = [
      (1e12, "T"),
      (1e9, "B"),
      (1e6, "M"),
      (1e3, "k")
    ]
    unit_suffix = ""

    if not isinstance(value, (int, float)):
      sys.stderr.write(f"Console error: non-numeric value passed to formatEuropeanNumber: {value}\n")
      return str(value)

    abs_val = abs(float(value))
    scaled_val = float(value)

    if options["use_abbreviation"]:
      for i in range(len(suffix_array)):
        local_threshold, local_suffix = suffix_array[i]
        if abs_val >= local_threshold:
          scaled_val = float(value)/local_threshold
          unit_suffix = local_suffix
          break

    if isinstance(value, int) and unit_suffix == "":
      formatted_str = str(value)
    else:
      formatted_str = f"{scaled_val:.{decimals}f}".replace(".", ",")

    #Return statement
    return f"{formatted_str}{unit_suffix}" if unit_suffix else formatted_str


  def formatLocalisedString (self, arg1_key, arg2_params_array=None):
    """
    @brief Format a localised CLI message replacing £1£, £2£, ... delimiters.
    @param arg1_key String key in the loaded localisation dictionary.
    @param arg2_params_array Optional list of replacement values.
    @return Formatted localised string.
    """
    #Convert from parameters
    key = arg1_key
    params_array = arg2_params_array if isinstance(arg2_params_array, list) else []

    #Declare local instance variables
    template_str = ""

    if not isinstance(key, str) or key == "":
      sys.stderr.write("Console error: empty localisation key provided.\n")
      return ""

    template_str = str(self.localisation_obj.get(key, key))
    for i in range(len(params_array)):
      local_placeholder = f"£{i + 1}£"
      local_val = params_array[i]
      if isinstance(local_val, float):
        local_text = self.formatEuropeanNumber(local_val, {"use_abbreviation": False})
      else:
        local_text = str(local_val)
      template_str = template_str.replace(local_placeholder, local_text)

    #Return statement
    return template_str


  def loadAllConfigs (self, arg1_config_subdir):
    """
    @brief Load areal_mask_config.json5 and the active localisation file from /localisation/.
    @param arg1_config_subdir Relative path under root_dir containing JSON5 config files.
    @return Dictionary containing areal_mask_config and localisation.
    """
    #Convert from parameters
    config_subdir = str(arg1_config_subdir or os.path.join("common", "areal_masks"))

    #Declare local instance variables
    areal_cfg_path = os.path.join(self.root_dir, config_subdir, "areal_mask_config.json5")
    locale_dir = "localisation"
    locale_path = ""

    self.areal_config_obj = self.loadJson5File(areal_cfg_path)
    locale_dir = str(self.areal_config_obj.get("paths", {}).get("localisation_dir", "localisation"))
    locale_path = os.path.join(self.root_dir, locale_dir, f"{self.locale}.json5")
    if os.path.exists(locale_path):
      self.localisation_obj = self.loadJson5File(locale_path)

    #Return statement
    return {
      "areal_mask_config": self.areal_config_obj,
      "localisation": self.localisation_obj
    }


  def loadJson5File (self, arg1_file_path):
    """
    @brief Parse a JSON or JSON5 file from disk safely without throwing unhandled exceptions.
    @param arg1_file_path Path to the JSON/JSON5 file.
    @return Parsed dictionary or empty dictionary upon error.
    """
    #Convert from parameters
    file_path = str(arg1_file_path or "")

    #Declare local instance variables
    parsed_obj = {}

    if not file_path or not os.path.exists(file_path):
      sys.stderr.write(f"Console error: configuration file not found: {file_path}\n")
      return parsed_obj

    try:
      with open(file_path, "r", encoding="utf-8") as local_fh:
        parsed_obj = pyjson5.decode(local_fh.read())
    except Exception as local_err:
      sys.stderr.write(f"Console error: failed decoding JSON5 file {file_path}: {local_err}\n")
      parsed_obj = {}

    #Return statement
    return parsed_obj if isinstance(parsed_obj, dict) else {}
