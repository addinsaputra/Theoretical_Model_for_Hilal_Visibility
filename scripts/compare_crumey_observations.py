"""Launch the corresponding hilal_visibility workflow."""
import _bootstrap  # noqa: F401
from hilal_visibility.studies.crumey_empirical import main

if __name__ == "__main__":
    raise SystemExit(main())
