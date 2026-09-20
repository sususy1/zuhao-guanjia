from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..auth import get_current_user
from .. import models, schemas
from ..platforms.registry import PLATFORM_REGISTRY

router = APIRouter(prefix="/api/platforms", tags=["平台"])


@router.get("", response_model=List[schemas.PlatformInfo])
def list_platforms(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    result = []
    for key, info in PLATFORM_REGISTRY.items():
        result.append(schemas.PlatformInfo(
            key=key,
            name=info["name"],
            icon=info["icon"],
            supported=info.get("adapter") is not None,
            description=info["description"],
        ))
    return result
