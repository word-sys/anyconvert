"""Module entry point for anyconvert when executed as a module (`python -m anyconvert`)."""

from __future__ import annotations

import sys
from anyconvert.cli import main

if __name__ == "__main__":
    sys.exit(main())
