from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.memory.db import get_database
from app.tongue_photos.repository import TonguePhotoRepository

router = APIRouter()


@router.get("/tongue-photos/{photo_id}")
async def get_tongue_photo(photo_id: str) -> Response:
    """Unauthenticated read-only capability URL (ADR 0007).

    LINE's servers fetch ImageMessage URLs without credentials, so this
    endpoint carries none; possession of the UUID4 is the authorization.
    Do NOT add listing/enumeration endpoints.
    """
    jpeg = await TonguePhotoRepository(get_database()).get_jpeg(photo_id)
    if jpeg is None:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(content=jpeg, media_type="image/jpeg")
