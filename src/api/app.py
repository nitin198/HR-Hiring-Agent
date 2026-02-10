"""Main FastAPI application."""

from contextlib import asynccontextmanager
import json
import os

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.routers import candidates, health, job_descriptions, reports, outlook, interviews
from src.config.settings import get_settings
from src.database.connection import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    await init_db()
    yield
    # Shutdown
    pass


app = FastAPI(
    title="AI Smart Hiring Agent",
    description="Autonomous AI agent for automated hiring decisions",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
# In production, replace ["*"] with specific allowed origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Configure specific origins for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers with /api prefix
app.include_router(health.router, prefix="/api")
app.include_router(job_descriptions.router, prefix="/api")
app.include_router(candidates.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(outlook.router, prefix="/api")
app.include_router(interviews.router, prefix="/api")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


# Mount static files
# Use current working directory to find static folder
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
# Go up 3 levels to reach project root
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
static_dir = os.path.join(project_root, "static")

print(f"Current directory: {current_dir}")
print(f"Project root: {project_root}")
print(f"Static directory: {static_dir}")
print(f"Static exists: {os.path.exists(static_dir)}")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    print(f"[OK] Static files mounted from: {static_dir}")
else:
    print(f"[X] Warning: Static directory not found at: {static_dir}")
    # Try alternative path
    alt_static = os.path.join(os.getcwd(), "static")
    print(f"Trying alternative path: {alt_static}")
    if os.path.exists(alt_static):
        app.mount("/static", StaticFiles(directory=alt_static), name="static")
        print(f"[OK] Static files mounted from: {alt_static}")


@app.get("/")
async def root():
    """Root endpoint - redirect to UI."""
    # Use the working directory to find static files
    alt_static = os.path.join(os.getcwd(), "static")
    if os.path.exists(alt_static):
        return FileResponse(os.path.join(alt_static, "index.html"))
    else:
        # Fallback to original static_dir
        return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/api")
async def api_info():
    """API info endpoint."""
    return {
        "name": "AI Smart Hiring Agent",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "job_descriptions": "/job-descriptions",
            "candidates": "/candidates",
            "reports": "/reports",
            "outlook": "/outlook",
            "interviews": "/interviews",
        },
    }


@app.get("/config.js")
async def frontend_config(request: Request) -> Response:
    """Return frontend configuration as JavaScript."""
    base_url = settings.api_base_url or str(request.base_url).rstrip("/")
    payload = {"API_BASE_URL": base_url}
    script = f"window.APP_CONFIG = {json.dumps(payload)};"
    return Response(content=script, media_type="application/javascript")
