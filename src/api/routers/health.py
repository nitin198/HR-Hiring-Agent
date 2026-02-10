"""Router for health check endpoints."""

from datetime import datetime

from fastapi import APIRouter
from src.api.schemas import HealthResponse
from src.llm.ollama_service import OllamaService

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=HealthResponse)
async def health_check() -> dict:
    """
    Health check endpoint.

    Returns:
        Health status with Ollama connection info
    """
    ollama = OllamaService()
    ollama_connected = True
    ollama_model = ollama.model

    try:
        # Try a simple invocation to verify connection
        # This is a lightweight check
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{ollama.base_url}/api/tags")
            if response.status_code != 200:
                ollama_connected = False
    except Exception:
        ollama_connected = False
        ollama_model = None

    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "ollama_connected": ollama_connected,
        "ollama_model": ollama_model,
    }