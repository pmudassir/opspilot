import json
from pathlib import Path

import pytest
from fastapi import FastAPI

FRONTEND_SNAPSHOT = Path(__file__).resolve().parents[2] / "frontend/src/lib/api/openapi.json"


def test_frontend_api_types_are_generated_from_the_current_api(app: FastAPI) -> None:
    """The frontend's TypeScript types come from this snapshot. If the API changes
    without regenerating it, the frontend would compile against a stale contract."""
    if not FRONTEND_SNAPSHOT.exists():
        pytest.skip("frontend not present")

    snapshot = json.loads(FRONTEND_SNAPSHOT.read_text())

    assert snapshot == app.openapi(), "API changed: run `npm run gen:api` in frontend/"
