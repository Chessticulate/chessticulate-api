"""app.crud

CRUD operations

Functions:
    get_user_by_name(name: str) -> models.User
    get_user_by_id(id_: str) -> models.User
    create_user(name: str, email: str, pswd: SecretStr) -> models.User
    login(name: str, pswd: SecretStr) -> str
    create_invitation(from_: str, to: str, game_type: str = models.GameType.CHESS.value)
        -> models.Invitation
    get_invitations(*, skip: int = 0, limit: int = 10, reverse: bool = False, **kwargs) -> list[models.Invitation]:
    validate_token(token: str) -> bool
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from pydantic import SecretStr
from sqlalchemy import select, update, exc

from chessticulate_api import models
from chessticulate_api.config import CONFIG
from chessticulate_api.db import async_session


def _hash_password(pswd: SecretStr) -> str:
    """Hash password using bcrypt."""
    return bcrypt.hashpw(  # pylint: disable=no-member
        pswd.get_secret_value(), bcrypt.gensalt()
    )


def _check_password(pswd: SecretStr, pswd_hash: str) -> bool:
    """Compare password with password hash using bcrypt."""
    return bcrypt.checkpw(  # pylint: disable=no-member
        pswd.get_secret_value(), pswd_hash
    )


def validate_token(token: str) -> dict:
    """Validate a JWT."""
    return jwt.decode(token, CONFIG.secret, CONFIG.algorithm)


async def get_user_by_name(name: str) -> models.User | None:
    """Retrieve user from database by user name."""
    async with async_session() as session:
        stmt = select(models.User).where(models.User.name == name, models.User.deleted == False)

        row = (await session.execute(stmt)).first()
        return row if row is None else row[0]


async def get_user_by_id(id_: int) -> models.User | None:
    """Retrieve user from database by user ID."""
    async with async_session() as session:
        stmt = select(models.User).where(models.User.id_ == id_, models.User.deleted == False)

        row = (await session.execute(stmt)).first()
        return row if row is None else row[0]


async def create_user(name: str, email: str, pswd: SecretStr) -> models.User:
    """
    Create a new user.

    Raises a sqlalchemy.exc.IntegrityError if either name or email is already present.
    """
    hashed_pswd = _hash_password(pswd)
    async with async_session() as session:
        user = models.User(name=name, email=email, password=hashed_pswd)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def delete_user(id_: int) -> bool:
    """
    Delete existing user.

    Returns True if user succesfully deleted, False if user
    does not exist or is already deleted. The user row is
    not actually deleted from the users table, but is only
    marked "deleted", and it's email and password removed.
    """
    async with async_session() as session:
        stmt = (
            update(models.User)
            .where(models.User.id_ == id_, models.User.deleted == False)
            .values(password=None, email=None, deleted=True)
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount == 1


async def login(name: str, pswd: SecretStr) -> str | None:
    """
    Validate user name and password.

    Returns None if bad login fails.
    Returns JWT in the form of a str on success.
    """
    user = await get_user_by_name(name)
    if user is None:
        return None
    if not _check_password(pswd, user.password):
        return None
    return jwt.encode(
        {
            "exp": datetime.now(tz=timezone.utc) + timedelta(days=CONFIG.token_ttl),
            "user_name": name,
            "user_id": user.id_,
        },
        CONFIG.secret,
    )


async def create_invitation(
    from_id: int, to_id: int, game_type: models.GameType = models.GameType.CHESS
) -> models.Invitation:
    """
    Create a new invitation.

    Raises a sqlalchemy.exc.IntegrityError if from_id or to_id do not exist.
    Does not check if the from_id or to_id have been marked deleted, that will
    have to be done separately.
    """
    async with async_session() as session:
        invitation = models.Invitation(
            from_id=from_id, to_id=to_id, game_type=game_type
        )
        session.add(invitation)
        await session.commit()
        await session.refresh(invitation)
        return invitation


async def get_invitations(
    *, skip: int = 0, limit: int = 10, reverse: bool = False, **kwargs
) -> list[models.Invitation]:
    """
    Retrieve a list of invitations from DB.

    Examples:
        # get invitation by ID
        get_invitations(id_=10)

        # get pending invitations addressed to user with ID 3
        get_invitations(skip=0, limit=5, to_id=3, status='PENDING')
    """
    async with async_session() as session:
        stmt = select(models.Invitation)
        for k, v in kwargs.items():
            stmt = stmt.where(getattr(models.Invitation, k) == v)

        if reverse:
            stmt = stmt.order_by(models.Invitation.date_sent.desc())
        else:
            stmt = stmt.order_by(models.Invitation.date_sent.asc())

        stmt = stmt.offset(skip).limit(limit)
        return [row[0] for row in (await session.execute(stmt)).all()]


async def cancel_invitation(id_: int) -> bool:
    """
    Cancel invitation.

    Returns False if invitation does not exist or does not have PENDING status.
    Returns True on success.
    """
    async with async_session() as session:
        stmt = (
            update(models.Invitation)
            .where(
                models.Invitation.id_ == id_,
                models.Invitation.status == models.InvitationStatus.PENDING,
            ).values(status=models.InvitationStatus.CANCELLED)
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount == 1


async def accept_invitation(id_: int) -> models.Game | None:
    """
    Accept pending invitation and create a new game.

    Returns None if invitation does not exist or does not have PENDING status.
    Returns a new game object on success.
    """
    async with async_session() as session:
        stmt = select(models.Invitation).where(
            models.Invitation.id_ == id_,
            models.Invitation.status == models.InvitationStatus.PENDING,
        )
        result = (await session.execute(stmt)).first()
        invitation = None if not result else result[0]
        if invitation is None:
            return None

        invitation.status = models.InvitationStatus.ACCEPTED
        new_game = models.Game(
            player_1=invitation.from_id,
            player_2=invitation.to_id,
            whomst=invitation.from_id,
            invitation_id=id_,
            game_type=invitation.game_type,
        )
        session.add(new_game)
        await session.commit()

        return new_game


async def decline_invitation(id_: int) -> bool:
    """
    Decline pending invitation.

    Returns False if invitation does not exist or does not have PENDING status.
    Returns True on success.
    """
    async with async_session() as session:
        stmt = (
            update(models.Invitation)
            .where(
                models.Invitation.id_ == id_,
                models.Invitation.status == models.InvitationStatus.PENDING,
            ).values(status=models.InvitationStatus.DECLINED)
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount == 1


async def get_game(id_: int) -> models.Game:
    """Retrieve game from database using game id"""
    async with async_session() as session:
        stmt = select(models.Game).where(models.Game.id_ == id_)

        row = (await session.execute(stmt)).first()
        return row if row is None else row[0]

