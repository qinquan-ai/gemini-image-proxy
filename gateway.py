import uvicorn

from src.api import create_app
from src.config.settings import Settings


settings = Settings.load_from_files()
settings.gateway.validate_remote_access()
app = create_app(settings=settings)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.gateway.bind_host,
        port=settings.gateway.port,
        workers=1,
    )
