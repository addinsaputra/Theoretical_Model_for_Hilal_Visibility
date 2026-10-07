"""Repository resources resolved independently of the working directory."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / 'data'
EPHEMERIS_PATH = DATA_DIR / 'ephemeris' / 'de440s.bsp'
OBSERVATIONS_PATH = DATA_DIR / 'observations' / 'bmkg_ccd.json'
OUTPUT_DIR = PROJECT_ROOT / 'outputs'
CACHE_DIR = PROJECT_ROOT / '.cache'
VALIDATION_DIR = PROJECT_ROOT / 'validation'
