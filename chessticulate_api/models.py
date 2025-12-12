"""chessticulate_api.models"""

import enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    func,
    sql,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from chessticulate_api import db


class Base(DeclarativeBase):  # pylint: disable=too-few-public-methods
    """Base SQLAlchemy ORM Class"""


class GameType(enum.Enum):
    """GameType Enum

    This enum contains the available game types.
    """

    CHESS = "CHESS"


class InvitationStatus(enum.StrEnum):
    """Invitation Status Enum"""

    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"


class ChallengeRequestStatus(enum.StrEnum):
    """Challenge Request Status Enum"""

    ACCEPTED = "ACCEPTED"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"


class GameResult(enum.StrEnum):
    """Game Result Enum"""

    CHECKMATE = "CHECKMATE"
    STALEMATE = "STALEMATE"
    INSUFFICIENTMATERIAL = "INSUFFICIENTMATERIAL"
    THREEFOLDREPETITION = "THREEFOLDREPETITION"
    FIFTYMOVERULE = "FIFTYMOVERULE"

    # not returned by shallowpink
    DRAWBYAGREEMENT = "DRAWBYAGREEMENT"
    RESIGNATION = "RESIGNATION"
    TIMEOUT = "TIMEOUT"


class User(Base):  # pylint: disable=too-few-public-methods
    """User SQL Model"""

    __tablename__ = "users"

    id_: Mapped[int] = mapped_column("id", primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
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
        DateTime,
        nullable=False,
        server_default=func.now(),  # pylint: disable=not-callable
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


class ChallengeRequest(Base):  # pylint: disable=too-few-public-methods
    """Challenge Request SQL Model"""

    __tablename__ = "challenge_requests"

    id_: Mapped[int] = mapped_column("id", primary_key=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),  # pylint: disable=not-callable
    )
    game_type: Mapped[str] = mapped_column(
        Enum(GameType), nullable=False, server_default=GameType.CHESS.value
    )
    status: Mapped[str] = mapped_column(
        Enum(ChallengeRequestStatus),
        nullable=False,
        server_default=ChallengeRequestStatus.PENDING.value,
    )
    fulfilled_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=True)


class Game(Base):  # pylint: disable=too-few-public-methods
    """Game SQL Model"""

    __tablename__ = "games"
    __table_args__ = (
        CheckConstraint(
            "(invitation_id IS NOT NULL) OR (challenge_id IS NOT NULL)",
            name="ck_game_invitation_or_challenge",
        ),
    )

    id_: Mapped[int] = mapped_column("id", primary_key=True)
    game_type: Mapped[str] = mapped_column(
        Enum(GameType), nullable=False, server_default=GameType.CHESS.value
    )
    date_started: Mapped[str] = mapped_column(
        DateTime,
        server_default=func.now(),  # pylint: disable=not-callable
        nullable=False,
    )
    invitation_id: Mapped[int] = mapped_column(
        ForeignKey("invitations.id"), nullable=True
    )
    challenge_id: Mapped[int] = mapped_column(
        ForeignKey("challenge_requests.id"), nullable=True
    )
    last_active: Mapped[str] = mapped_column(
        DateTime,
        server_default=func.now(),  # pylint: disable=not-callable
        nullable=False,
    )
    white: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    black: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    whomst: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    winner: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql.true()
    )
    result: Mapped[str] = mapped_column(
        Enum(GameResult),
        nullable=True,
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


class Move(Base):  # pylint: disable=too-few-public-methods
    """Move SQL Model"""

    __tablename__ = "moves"

    id_: Mapped[int] = mapped_column("id", primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    timestamp: Mapped[str] = mapped_column(
        DateTime,
        server_default=func.now(),  # pylint: disable=not-callable
        nullable=False,
    )
    movestr: Mapped[str] = mapped_column(String, nullable=False)
    fen: Mapped[str] = mapped_column(String, nullable=False)


async def init_db():
    """Submit DDL to database"""
    async with db.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
