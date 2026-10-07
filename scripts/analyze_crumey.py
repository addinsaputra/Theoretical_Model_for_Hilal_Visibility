"""Launch the corresponding hilal_visibility workflow."""
import _bootstrap  # noqa: F401
from hilal_visibility.studies.diagnostics import main

if __name__ == "__main__":
    raise SystemExit(main())
