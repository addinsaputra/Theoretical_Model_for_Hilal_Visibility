"""Allow scripts to run from a source checkout without an editable install."""
from pathlib import Path
import sys

SOURCE_DIR = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SOURCE_DIR))
from hilal_visibility.console import configure_console_encoding

configure_console_encoding()
