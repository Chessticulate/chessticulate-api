"""chessticulate_api.app"""

import importlib.metadata
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from chessticulate_api import crud, db, models, routers, schemas
from chessticulate_api.config import CONFIG


@asynccontextmanager
async def lifespan(app_: FastAPI):
    """Setup DB and Redis"""
    await models.init_db()

    app_.state.redis = Redis.from_url(
        CONFIG.redis_url,
        decode_responses=True,
    )

    try:
        yield
    finally:
        await app_.state.redis.aclose()
        await db.async_engine.dispose()


app = FastAPI(
    title=CONFIG.app_name,
    lifespan=lifespan,
    version=importlib.metadata.version("chessticulate_api"),
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=CONFIG.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routers.user_router)
app.include_router(routers.invitation_router)
app.include_router(routers.game_router)
app.include_router(routers.challenge_router)


@app.get("/", include_in_schema=False)
async def docs_redirect():
    """Root endpoint"""
    return RedirectResponse(url="/docs")


@app.post("/login")
async def login(
    session: Annotated[AsyncSession, Depends(db.session)], payload: schemas.LoginRequest
) -> schemas.LoginResponse:
    """Given valid user credentials, generate JWT."""
    if not (token := await crud.login(session, payload.name, payload.password)):
        raise HTTPException(status_code=401, detail="invalid credentials")
    return schemas.LoginResponse(jwt=token)


@app.post("/signup", status_code=201)
async def signup(
    session: Annotated[AsyncSession, Depends(db.session)],
    payload: schemas.CreateUserRequest,
) -> schemas.GetOwnUserResponse:
    """Create a new user account."""
    if await crud.get_users(session, name=payload.name):
        raise HTTPException(
            status_code=400, detail="user with same name already exists"
        )
    if await crud.get_users(session, name=payload.email):
        raise HTTPException(
            status_code=400, detail="user with same name already exists"
        )
    user = await crud.create_user(
        session, payload.name, payload.email, payload.password
    )

    return schemas.GetOwnUserResponse(**vars(user))
