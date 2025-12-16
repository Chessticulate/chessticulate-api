from copy import copy
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from chessticulate_api import app, config, crud, db, models

FAKE_USER_DATA = [
    {
        "name": "fakeuser1",
        "password": "fakepswd1",
        "email": "fakeuser1@fakeemail.com",
    },
    {
        "name": "fakeuser2",
        "password": "fakepswd2",
        "email": "fakeuser2@fakeemail.com",
    },
    {
        "name": "fakeuser3",
        "password": "fakepswd3",
        "email": "fakeuser3@fakeemail.com",
    },
    {
        "name": "fakeuser4",
        "password": "fakepswd4",
        "email": "fakeuser4@fakeemail.com",
        "deleted": True,
    },
    {
        "name": "fakeuser5",
        "password": "fakepswd5",
        "email": "fakeuser5@fakeemail.com",
        "wins": 2,
    },
    {
        "name": "fakeuser6",
        "password": "fakepswd6",
        "email": "fakeuser6@fakeemail.com",
        "wins": 1,
    },
]


FAKE_INVITATION_DATA = [
    {
        "from_id": 1,
        "to_id": 2,
        "game_type": models.GameType.CHESS,
        "status": models.InvitationStatus.ACCEPTED,
    },
    {
        "from_id": 3,
        "to_id": 1,
        "game_type": models.GameType.CHESS,
        "status": models.InvitationStatus.ACCEPTED,
    },
    {
        "from_id": 2,
        "to_id": 3,
        "game_type": models.GameType.CHESS,
        "status": models.InvitationStatus.ACCEPTED,
    },
    {
        "from_id": 1,
        "to_id": 2,
        "game_type": models.GameType.CHESS,
        "status": models.InvitationStatus.PENDING,
    },
    {
        "from_id": 1,
        "to_id": 2,
        "game_type": models.GameType.CHESS,
        "status": models.InvitationStatus.CANCELLED,
    },
    {
        "from_id": 1,
        "to_id": 2,
        "game_type": models.GameType.CHESS,
        "status": models.InvitationStatus.DECLINED,
    },
    {
        "from_id": 4,
        "to_id": 1,
        "game_type": models.GameType.CHESS,
        "status": models.InvitationStatus.PENDING,
    },
    {
        "from_id": 2,
        "to_id": 1,
        "game_type": models.GameType.CHESS,
        "status": models.InvitationStatus.PENDING,
    },
]


FAKE_GAME_DATA = [
    {
        "invitation_id": 1,
        "is_active": True,
        "white": 1,
        "black": 2,
        "whomst": 1,
    },
    {
        "invitation_id": 2,
        "is_active": False,
        "white": 3,
        "black": 1,
        "whomst": 3,
    },
    {
        "invitation_id": 3,
        "is_active": True,
        "white": 2,
        "black": 3,
        "whomst": 2,
    },
]

FAKE_MOVE_DATA = [
    {
        "user_id": 1,
        "game_id": 1,
        "movestr": "e4",
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
    },
    {
        "user_id": 3,
        "game_id": 2,
        "movestr": "Nxe4",
        "fen": "rnbqkb1r/pp2pppp/3p4/2p5/2B1N3/5N2/PPPP1PPP/R1BQK2R b KQkq - 0 1",
    },
    {
        "user_id": 2,
        "game_id": 3,
        "movestr": "bxa2",
        "fen": "r3kb1r/p3p1pp/1pn2p1n/2p5/1P2q1P1/2P2N2/b2QBP1P/1RB1K2R w Kkq - 0 1",
    },
]


@pytest.fixture(scope="session", autouse=True)
def fake_app_secret():
    config.CONFIG.jwt_secret = "fake_secret"


@pytest.fixture
def fake_user_data():
    return copy(FAKE_USER_DATA)


@pytest.fixture(scope="session")
def fake_invitation_data():
    return copy(FAKE_INVITATION_DATA)


@pytest.fixture(scope="session")
def fake_game_data():
    return copy(FAKE_GAME_DATA)


@pytest_asyncio.fixture(autouse=True)
async def override_db_session_dependency():
    """
    db.session() is an @asynccontextmanager, so calling it returns a context manager
    object (not an async-generator dependency). FastAPI's Depends() expects a
    yield-style dependency it can drive.

    In tests, we override db.session with a wrapper that:
      - enters your context manager (async with db.session())
      - yields a real AsyncSession to the endpoint
      - exits the context manager after the request (triggering your commit)
    """

    async def _override():
        async with db.session() as sesh:
            yield sesh

    app.dependency_overrides[db.session] = _override
    yield
    app.dependency_overrides.pop(db.session, None)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with db.session() as sesh:
        yield sesh


@pytest_asyncio.fixture
async def token(session: AsyncSession) -> str:
    fakeuser1 = FAKE_USER_DATA[0]
    token = await crud.login(
        session,
        fakeuser1["name"],
        SecretStr(fakeuser1["password"]),
    )
    assert token is not None
    return token


async def _init_fake_data():
    await db.async_engine.dispose()

    db.async_engine = db.create_async_engine(
        config.CONFIG.sql_conn_str, echo=config.CONFIG.sql_echo
    )
    db.async_session = db.async_sessionmaker(db.async_engine, expire_on_commit=False)
    await models.init_db()

    async with db.async_session() as session:
        await session.execute(text("PRAGMA foreign_keys = ON;"))
        await session.commit()

    async with db.async_session() as session:
        for data in FAKE_USER_DATA:
            data_copy = data.copy()
            pswd = crud._hash_password(SecretStr(data_copy.pop("password")))
            user = models.User(**data_copy, password=pswd)
            session.add(user)
        await session.commit()

    async with db.async_session() as session:
        for data in FAKE_INVITATION_DATA:
            invitation = models.Invitation(**data)
            session.add(invitation)
        await session.commit()

    async with db.async_session() as session:
        for data in FAKE_GAME_DATA:
            game = models.Game(**data)
            session.add(game)
        await session.commit()

    async with db.async_session() as session:
        for data in FAKE_MOVE_DATA:
            move = models.Move(**data)
            session.add(move)
        await session.commit()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def init_fake_data():
    await _init_fake_data()


@pytest_asyncio.fixture
async def restore_fake_data_after():
    yield
    await _init_fake_data()


@pytest_asyncio.fixture
async def client():
    app.state.redis = AsyncMock(name="FakeRedis")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
