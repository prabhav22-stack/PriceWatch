"""Root entry point for Render Web Service and local execution."""

import sys
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from pricewatch.entrypoints.web_server import main

if __name__ == "__main__":
    main()
