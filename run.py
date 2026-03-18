import uvicorn
from app.config import get_settings


def main():
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        reload_includes=["*.py", "*.yaml", "*.env"],
    )


if __name__ == "__main__":
    main()
