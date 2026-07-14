from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.schemas import TongueDescription, TonguePhoto

COLLECTION = "tongue_photos"


class TonguePhotoRepository:
    """Standalone thesis-dataset store (docs/adr/0007-tongue-photo-dataset-and-echo.md),
    deliberately outside the memory architecture: documents survive
    Consultation close and gate-failed discards.

    Insert-after-detect, patch-after-describe. Deliberately NO listing or
    enumeration methods: the capability URL (UUID4 photo_id) is the only
    read path, and possession of the UUID is the authorization.
    """

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db[COLLECTION]

    async def insert(self, photo: TonguePhoto) -> None:
        # model_dump keeps `image` as bytes; pymongo stores bytes as BSON
        # Binary subtype 0 -- no base64, no explicit Binary wrapper needed.
        await self._collection.insert_one(photo.model_dump())

    async def set_description(self, photo_id: str, description: TongueDescription) -> None:
        await self._collection.update_one(
            {"photo_id": photo_id}, {"$set": {"description": description.model_dump()}}
        )

    async def get_jpeg(self, photo_id: str) -> bytes | None:
        doc = await self._collection.find_one({"photo_id": photo_id}, {"image": 1})
        return bytes(doc["image"]) if doc else None
