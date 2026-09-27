import uuid

from pydantic import BaseModel

from app.departments.models import DEPARTMENT_NAME_MAX_LENGTH
from app.schemas import StrictRequest, trimmed_str


class DepartmentOut(BaseModel):
    id: uuid.UUID
    name: str


class CreateDepartmentRequest(StrictRequest):
    name: trimmed_str(DEPARTMENT_NAME_MAX_LENGTH)  # type: ignore[valid-type]
