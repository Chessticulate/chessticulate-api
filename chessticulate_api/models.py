"""chessticulate_api.models"""

import enum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, func, sql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from chessticulate_api import db


class Base(DeclarativeBase):  # pylint: disable=too-few-public-methods
    """Base SQLAlchemy ORM Class"""


class GameType(enum.Enum):
    """GameType Enum

    This enum contains the available game types.
    """

    CHESS = "CHESS"


class InvitationStatus(enum.Enum):
    """Invitation Response Enum"""

    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"


class GameStatus(enum.Enum):
    """Game Status Enum"""

    ACTIVE = "ACTIVE"
    DRAW = "DRAW"
    WHITEWINS = "WHITEWINS"
    BLACKWINS = "BLACKWINS"


class User(Base):  # pylint: disable=too-few-public-methods
    """User SQL Model"""

    __tablename__ = "users"

    id_: Mapped[int] = mapped_column("id", primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String, nullable=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=True)
    deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql.false()
    )
    date_joined: Mapped[str] = mapped_column(
        DateTime,
        server_default=func.now(),  # pylint: disable=not-callable
        nullable=False,
    )
    wins: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    draws: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    losses: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)


class Invitation(Base):  # pylint: disable=too-few-public-methods
    """Invitation SQL Model"""

    __tablename__ = "invitations"

    id_: Mapped[int] = mapped_column("id", primary_key=True)
    date_sent: Mapped[str] = mapped_column(
        DateTime, server_default=func.now()  # pylint: disable=not-callable
    )
    date_answered: Mapped[str] = mapped_column(DateTime, nullable=True)
    from_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    to_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    game_type: Mapped[str] = mapped_column(Enum(GameType), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(InvitationStatus),
        nullable=False,
        server_default=InvitationStatus.PENDING.value,
    )


# pylint: disable=not-callable
# pylint: disable=too-few-public-methods
class Game(Base):
    """Game SQL Model"""

    __tablename__ = "games"

    id_: Mapped[int] = mapped_column("id", primary_key=True)
    game_type: Mapped[str] = mapped_column(
        Enum(GameType), nullable=False, server_default=GameType.CHESS.value
    )
    date_started: Mapped[str] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=True,
    )
    invitation_id: Mapped[int] = mapped_column(
        ForeignKey("invitations.id"), nullable=False
    )
    date_ended: Mapped[str] = mapped_column(DateTime, nullable=True)
    last_active: Mapped[str] = mapped_column(DateTime, nullable=True)
    player_1: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    player_2: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    whomst: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    winner: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(GameStatus),
        nullable=False,
        server_default=GameStatus.ACTIVE.value,
    )
    fen: Mapped[str] = mapped_column(
        String,
        nullable=False,
        server_default=("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
    )
    states: Mapped[str] = mapped_column(
        String,
        nullable=False,
        server_default=("{}"),
    )


class Move(Base):
    """Move SQL Model"""

    __tablename__ = "moves"

    id_: Mapped[int] = mapped_column("id", primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    timestamp: Mapped[str] = mapped_column(
        DateTime,
        server_default=func.now(),  # pylint: disable=not-callable
        nullable=True,
    )
    movestr: Mapped[str] = mapped_column(String, nullable=False)
    fen: Mapped[str] = mapped_column(String, nullable=False)


async def init_db():
    """Submit DDL to database"""
    async with db.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
