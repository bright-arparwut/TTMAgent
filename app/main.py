from fastapi import FastAPI

from app.line.router import router as line_router
from app.tongue_photos.router import router as tongue_photos_router

app = FastAPI(title="TTM Consultation Assistant")
app.include_router(line_router)
app.include_router(tongue_photos_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
