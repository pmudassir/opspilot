"""Per-run request handles. The model sees R1, R2, ... and never a database id.

A ref only exists for a request a tool already showed to this user in this run, and
using one always re-queries with the organization and the user's visibility: a ref is
a pointer, never a permission.
"""

import uuid


class RefRegistry:
    """Deliberately stateful: it lives for one assistant run and is then discarded."""

    def __init__(self) -> None:
        self._ids: dict[str, uuid.UUID] = {}
        self._refs: dict[uuid.UUID, str] = {}

    def ref_for(self, request_id: uuid.UUID) -> str:
        """The same request always gets the same ref within a run."""
        if request_id not in self._refs:
            ref = f"R{len(self._refs) + 1}"
            self._refs[request_id] = ref
            self._ids[ref] = request_id
        return self._refs[request_id]

    def resolve(self, ref: str) -> uuid.UUID | None:
        return self._ids.get(ref.strip().upper())

    def as_dict(self) -> dict[str, uuid.UUID]:
        return dict(self._ids)
