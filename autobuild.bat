@echo off
echo Building distribution package...
python core\server\table_converter.py
python core\server\ArealMaskGenerator.py
echo Build complete.
