"""chessticulate_api.db"""

import contextlib
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from chessticulate_api.config import CONFIG

async_engine = create_async_engine(
    CONFIG.sql_conn_str, pool_pre_ping=True, echo=CONFIG.sql_echo
)

async_session = async_sessionmaker(async_engine, expire_on_commit=False)


@contextlib.asynccontextmanager
async def session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as sesh:
        yield sesh
        await sesh.commit()
