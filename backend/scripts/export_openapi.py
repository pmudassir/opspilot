"""Print the API's OpenAPI schema as JSON (input for frontend type generation).

Usage (from backend/): uv run python -m scripts.export_openapi > <file>
"""

import json
import sys

from app.main import app

json.dump(app.openapi(), sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
