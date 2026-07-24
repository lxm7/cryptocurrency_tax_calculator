"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from taxcalc.web.routes import chat


def create_app() -> FastAPI:
    app = FastAPI(title="crypto-tax-calc API", version="0.1.0")
    app.include_router(chat.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
