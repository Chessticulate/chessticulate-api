"""chessticulate_api.db"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from chessticulate_api.config import CONFIG

async_engine = create_async_engine(
    CONFIG.sql_conn_str,
    echo=CONFIG.sql_echo,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(async_engine, expire_on_commit=False)


async def session() -> AsyncGenerator[AsyncSession, None]:
    """Async session gnerator"""
    async with async_session() as sesh:
        yield sesh
        # await sesh.commit()
