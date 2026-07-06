from functools import lru_cache

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import Settings, get_settings


@lru_cache
def get_client() -> AsyncIOMotorClient:
    settings = get_settings()
    return AsyncIOMotorClient(settings.mongodb_uri)


def get_database(settings: Settings | None = None) -> AsyncIOMotorDatabase:
    settings = settings or get_settings()
    return get_client()[settings.mongodb_db_name]
