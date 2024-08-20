from copy import copy

import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.orm import Session

from chessticulate_api import config, crud, db, models

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
        "white": 1,
        "black": 2,
        "whomst": 1,
    },
    {
        "invitation_id": 2,
        "white": 3,
        "black": 1,
        "whomst": 3,
    },
    {
        "invitation_id": 3,
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


@pytest.fixture
def fake_app_secret(scope="session", autouse=True):
    config.CONFIG.jwt_secret = "fake_secret"


@pytest.fixture
def fake_user_data():
    return copy(FAKE_USER_DATA)


@pytest.fixture
def fake_invitation_data(scope="session"):
    return copy(FAKE_INVITATION_DATA)


@pytest.fixture
def fake_game_data(scope="session"):
    return copy(FAKE_GAME_DATA)


@pytest_asyncio.fixture
async def token(scope="session"):
    fakeuser1 = FAKE_USER_DATA[0]
    return await crud.login(fakeuser1["name"], SecretStr(fakeuser1["password"]))


async def _init_fake_data():
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
