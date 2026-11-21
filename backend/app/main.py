"""FastAPI app: serves the website and the JSON API. Run from the repo root:

    uvicorn backend.app.main:app --reload

Website:  http://localhost:8000
API docs: http://localhost:8000/docs
"""

from fastapi import APIRouter, FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .catalog import APPLIANCES, PRIORITIES
from .config import ROOT_DIR, settings
from .image_utils import InvalidImageError, preprocess_image
from .llm import LLMError, get_client
from .pipeline import generate_meals
from .schemas import DetectResponse, GenerateRequest, GenerateResponse

FRONTEND_DIR = ROOT_DIR / "frontend"
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}  # HEIC needs an extra Pillow plugin

app = FastAPI(title="FridgeToDinner API", version="0.2.0")
api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> dict:
    return {"status": "ok", "mock_mode": settings.mock_mode,
            "model": None if settings.mock_mode else settings.model}


@api.get("/options")
def options() -> dict:
    """Choices the website shows, as {key: label}."""
    return {"appliances": APPLIANCES, "priorities": PRIORITIES}


@api.post("/detect", response_model=DetectResponse)
async def detect(photo: UploadFile = File(..., description="Photo of the inside of a fridge")) -> DetectResponse:
    """Step 1: fridge photo -> ingredient list (the user can edit it before step 2)."""
    if photo.content_type and photo.content_type not in ALLOWED_TYPES:
        raise HTTPException(415, "Unsupported photo type. Please use a JPEG, PNG or WebP image "
                                 "(iPhone HEIC photos need to be converted first).")
    data = await photo.read()
    try:
        jpeg = preprocess_image(data, settings.max_image_edge)
    except InvalidImageError as exc:
        raise HTTPException(400, f"Could not read the photo: {exc}") from exc

    client = get_client()
    try:
        ingredients, usage = await run_in_threadpool(client.detect, jpeg)
    except LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    return DetectResponse(ingredients=ingredients, usage=usage, mock=client.mock)


@api.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    """Step 2: (edited) ingredients + appliances + priorities -> validated meals."""
    if not req.ingredients:
        raise HTTPException(400, "Add at least one ingredient.")
    unknown = [a for a in req.appliances if a not in APPLIANCES]
    if unknown:
        raise HTTPException(400, f"Unknown appliance(s): {', '.join(unknown)}")
    try:
        return await run_in_threadpool(generate_meals, req)
    except LLMError as exc:
        raise HTTPException(502, str(exc)) from exc


app.include_router(api)

# ---------------------------------------------------------------- website
if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")
