from fastapi import APIRouter
from app.api.v1 import (
    auth, users, importing, dashboard, forecasts, overrides, agents, upload,
    progress, preview, history, actuals, generated,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(importing.router)
api_router.include_router(dashboard.router)
api_router.include_router(forecasts.router)
api_router.include_router(overrides.router)
api_router.include_router(agents.router)
api_router.include_router(upload.router)
api_router.include_router(progress.router)
api_router.include_router(preview.router)
api_router.include_router(history.router)
api_router.include_router(actuals.router)
api_router.include_router(generated.router)
