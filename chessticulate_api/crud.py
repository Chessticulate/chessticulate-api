"""app.crud

CRUD operations

Functions:
    get_user_by_name(name: str) -> models.User
    get_user_by_id(id_: str) -> models.User
    create_user(name: str, email: str, pswd: SecretStr) -> models.User
    login(name: str, pswd: SecretStr) -> str
    create_invitation(from_: str, to: str, game_type: str = models.GameType.CHESS.value)
        -> models.Invitation
    get_invitations(*, skip: int = 0, limit: int = 10, reverse: bool = False, **kwargs)
        -> list[models.Invitation]:
    validate_token(token: str) -> bool
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from pydantic import SecretStr
from sqlalchemy import select, update

from chessticulate_api import db, models
from chessticulate_api.config import CONFIG


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


async def get_users(
    *,
    skip: int = 0,
    limit: int = 10,
    order_by: str = "date_joined",
    reverse: bool = False,
    **kwargs,
) -> list[models.Invitation]:
    """
    Retrieve a list of users from DB.

    Examples:
        # get user by name or ID
        get_users(id_=10)
        get_users(name="user10")

        # get top five winning users
        get_users(skip=0, limit=5, reverse=True, order_by="wins")
    """
    async with db.async_session() as session:
        stmt = select(models.User)
        for k, v in kwargs.items():
            stmt = stmt.where(getattr(models.User, k) == v)

        order_by_attr = getattr(models.User, order_by)
        if reverse:
            order_by_attr = order_by_attr.desc()
        else:
            order_by_attr = order_by_attr.asc()
        stmt = stmt.order_by(order_by_attr)

        stmt = stmt.offset(skip).limit(limit)
        return [row[0] for row in (await session.execute(stmt)).all()]


async def create_user(name: str, email: str, pswd: SecretStr) -> models.User:
    """
    Create a new user.

    Raises a sqlalchemy.exc.IntegrityError if either name or email is already present.
    """
    hashed_pswd = _hash_password(pswd)
    async with db.async_session() as session:
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
    async with db.async_session() as session:
        stmt = (
            # pylint: disable=singleton-comparison
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

    Returns None if login fails.
    Returns JWT in the form of a str on success.
    """
    result = await get_users(name=name, deleted=False)
    if len(result) == 0:
        return None
    user = result[0]

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
    async with db.async_session() as session:
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
    async with db.async_session() as session:
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
    async with db.async_session() as session:
        stmt = (
            update(models.Invitation)
            .where(
                models.Invitation.id_ == id_,
                models.Invitation.status == models.InvitationStatus.PENDING,
            )
            .values(status=models.InvitationStatus.CANCELLED)
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
    async with db.async_session() as session:
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
    async with db.async_session() as session:
        stmt = (
            update(models.Invitation)
            .where(
                models.Invitation.id_ == id_,
                models.Invitation.status == models.InvitationStatus.PENDING,
            )
            .values(status=models.InvitationStatus.DECLINED)
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount == 1


async def get_games(
    *,
    skip: int = 0,
    limit: int = 10,
    order_by: str = "date_started",
    reverse: bool = False,
    **kwargs,
) -> list[models.Game]:
    """
    Retrieve a list of games from DB.

    Examples:
        # get game by ID
        get_games(id_=10)

        # list 10 games where player_1 id = 5
        get_games(player_1=5, skip=0, limit=10)

    """
    async with db.async_session() as session:
        stmt = select(models.Game)
        for k, v in kwargs.items():
            stmt = stmt.where(getattr(models.Game, k) == v)

        order_by_attr = getattr(models.Game, order_by)
        if reverse:
            order_by_attr = order_by_attr.desc()
        else:
            order_by_attr = order_by_attr.asc()
        stmt = stmt.order_by(order_by_attr)

        stmt = stmt.offset(skip).limit(limit)
        return [row[0] for row in (await session.execute(stmt)).all()]

async def do_move(id_: int, new_state: str) -> bool:

    """ updates game in database using given state """
    
    async with db.async_session() as session:
        stmt = (
            update(models.Game)
            .where(models.Game.id_ == id_)
            .values(state=new_state)
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount == 1
