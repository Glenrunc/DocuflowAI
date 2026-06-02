from fastapi import APIRouter

from ..schema_def import load_schema

router = APIRouter(prefix="/api", tags=["schemas"])


@router.get("/schemas")
def get_schemas():
    return load_schema().model_dump()
