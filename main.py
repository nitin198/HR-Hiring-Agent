"""Main entry point for the AI Smart Hiring Agent."""

import uvicorn

from src.config.settings import get_settings

settings = get_settings()


def main():
    """Run the FastAPI application."""
    uvicorn.run(
        "src.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
    )


if __name__ == "__main__":
    main()