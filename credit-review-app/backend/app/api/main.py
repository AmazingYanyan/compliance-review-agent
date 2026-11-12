from fastapi import APIRouter

from app.api.routes import assets, auth, capabilities, checklist, files, health, runs, tasks

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(capabilities.router)
api_router.include_router(checklist.router)
api_router.include_router(tasks.router)
api_router.include_router(files.router)
api_router.include_router(assets.router)
api_router.include_router(runs.router)
api_router.include_router(health.router)
