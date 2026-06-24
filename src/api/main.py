from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.v1 import auth, candidates, match, processes
from src.config import settings
from src.domain.shared.exceptions import (
    BusinessRuleException,
    ConflictException,
    DomainException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)

app = FastAPI(
    title="RIWI MATCH API",
    version="1.0.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_production else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Manejadores de excepciones de dominio → HTTP

@app.exception_handler(UnauthorizedException)
async def unauthorized_handler(_: Request, exc: UnauthorizedException) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": str(exc)})


@app.exception_handler(ForbiddenException)
async def forbidden_handler(_: Request, exc: ForbiddenException) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(NotFoundException)
async def not_found_handler(_: Request, exc: NotFoundException) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ConflictException)
async def conflict_handler(_: Request, exc: ConflictException) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(BusinessRuleException)
async def business_rule_handler(_: Request, exc: BusinessRuleException) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(DomainException)
async def domain_handler(_: Request, exc: DomainException) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# Routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(processes.router, prefix="/api/v1")
app.include_router(candidates.router, prefix="/api/v1")
app.include_router(match.router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
async def health() -> dict:
    return {"status": "ok", "env": settings.app_env}
