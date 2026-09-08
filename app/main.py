import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import JSONResponse

from app.config import Settings
from app.monitor import Monitor
from app.notify import NotificationError
from app.scraper import PriceReadError


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    monitor = Monitor(settings)
    app = FastAPI(title="Ombré Leather price monitor", version="1.0.0")
    app.state.monitor = monitor
    bearer = HTTPBearer(auto_error=False)

    def authenticate(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        token = settings.api_token.get_secret_value()
        if not token:
            raise HTTPException(503, "API_TOKEN is not configured")
        if credentials is None or not secrets.compare_digest(credentials.credentials, token):
            raise HTTPException(401, "Invalid API token", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/status", dependencies=[Depends(authenticate)])
    async def status():
        return {"last_result": monitor.last_result, "last_error": monitor.last_error,
                "last_attempt_at": monitor.last_attempt_at, "running": monitor.lock.locked()}

    @app.post("/check", dependencies=[Depends(authenticate)])
    async def check(dry_run: bool = False):
        if monitor.lock.locked():
            raise HTTPException(409, "A check is already running")
        try:
            report = await monitor.check(dry_run=dry_run)
            return JSONResponse(status_code=200 if report.ok else 502,
                                content=report.model_dump(mode="json"))
        except (PriceReadError, NotificationError) as exc:
            raise HTTPException(502, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from None

    return app


app = create_app()
