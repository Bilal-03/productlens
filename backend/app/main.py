from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import get_settings

settings = get_settings()
app = FastAPI(
    title="ProductLens AI API",
    version="0.1.0",
    description="Governed, read-only product analytics and evidence-backed investigation API",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "Last-Event-ID",
        "X-ProductLens-Session",
        "X-ProductLens-Access",
    ],
)
app.include_router(router, prefix=settings.api_prefix)


@app.middleware("http")
async def request_size_limit(request: Request, call_next):  # type: ignore[no-untyped-def]
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 32_768:
        return JSONResponse(status_code=413, content={"detail": "Request body is too large"})
    return await call_next(request)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "ProductLens AI", "docs": "/docs", "health": f"{settings.api_prefix}/health"}
