"""chessticulate_api.app"""

import importlib
from contextlib import asynccontextmanager

import sqlalchemy
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from chessticulate_api import crud, models, routers, schemas
from chessticulate_api.config import CONFIG


@asynccontextmanager
async def lifespan(*args):  # pylint: disable=unused-argument
    """Setup DB"""
    await models.init_db()
    yield


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
async def login(payload: schemas.LoginRequest) -> schemas.LoginResponse:
    """Given valid user credentials, generate JWT."""
    if not (token := await crud.login(payload.name, payload.password)):
        raise HTTPException(status_code=401, detail="invalid credentials")
    return {"jwt": token}


@app.post("/signup", status_code=201)
async def signup(payload: schemas.CreateUserRequest) -> schemas.GetOwnUserResponse:
    """Create a new user account."""
    try:
        user = await crud.create_user(payload.name, payload.email, payload.password)
    except sqlalchemy.exc.IntegrityError as ie:
        raise HTTPException(
            status_code=400, detail="user with same name or email already exists"
        ) from ie

    return vars(user)
