"""chessticulate_api.crud"""

import random
from datetime import datetime, timedelta, timezone
from typing import TypeAlias, NamedTuple

import bcrypt
import jwt
from pydantic import SecretStr
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from chessticulate_api import db, models, schemas
from chessticulate_api.config import CONFIG

WhiteUsername: TypeAlias = str
BlackUsername: TypeAlias = str
RequesterUsername: TypeAlias = str
MoveList: TypeAlias = list[str]


def _hash_password(pswd: SecretStr) -> str:
    """Hash password using bcrypt."""
    return bcrypt.hashpw(  # pylint: disable=no-member  # pyright: ignore
        pswd.get_secret_value(), bcrypt.gensalt()
    )


def _check_password(pswd: SecretStr, pswd_hash: str) -> bool:
    """Compare password with password hash using bcrypt."""
    return bcrypt.checkpw(  # pylint: disable=no-member  # pyright: ignore
        pswd.get_secret_value(), pswd_hash
    )


async def get_users(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 10,
    order_by: str = "date_joined",
    reverse: bool = False,
    **kwargs,
) -> list[models.User]:
    """
    Retrieve a list of users from DB.

    Examples:
        # get user by name or ID
        get_users(id_=10)
        get_users(name="user10")

        # get top five winning users
        get_users(skip=0, limit=5, reverse=True, order_by="wins")
    """
    stmt = select(models.User)
    for k, v in kwargs.items():
        stmt = stmt.where(getattr(models.User, k) == v)

    order_attr = getattr(models.User, order_by)
    stmt = stmt.order_by(order_attr.desc() if reverse else order_attr.asc())
    stmt = stmt.offset(skip).limit(limit)

    return (await session.execute(stmt)).scalars().all()


async def create_user(
    session: AsyncSession, name: str, email: str, pswd: SecretStr
) -> models.User:
    """
    Create a new user.

    Raises a sqlalchemy.exc.IntegrityError if either name or email is already present.
    """
    hashed_pswd = _hash_password(pswd)
    user = models.User(name=name, email=email, password=hashed_pswd)
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def delete_user(session: AsyncSession, id_: int) -> bool:
    """
    Delete existing user.

    Returns True if user succesfully deleted, False if user
    does not exist or is already deleted. The user row is
    not actually deleted from the users table, but is only
    marked "deleted", and it's email and password removed.
    """
    stmt = (
        # pylint: disable=singleton-comparison
        update(models.User)
        .where(models.User.id_ == id_, models.User.deleted == False)
        .values(password=None, email=None, deleted=True)
    )
    result = await session.execute(stmt)
    return result.rowcount == 1  # pyright: ignore


async def login(
    session: AsyncSession, name: str, submitted_pswd: SecretStr
) -> str | None:
    """
    Validate user name and password.

    Returns None if login fails.
    Returns JWT in the form of a str on success.
    """
    result = await get_users(session, name=name, deleted=False)
    if len(result) == 0:
        return None
    user = result[0]

    if not _check_password(submitted_pswd, user.password):
        return None

    payload = schemas.Credentials(
        exp=datetime.now(tz=timezone.utc) + timedelta(days=CONFIG.jwt_ttl),
        user_name=user.name,
        user_id=user.id_,
    )

    return jwt.encode(
        payload.model_dump(),
        CONFIG.jwt_secret,
    )


async def create_invitation(
    session: AsyncSession,
    from_id: int,
    to_id: int,
    game_type: models.GameType = models.GameType.CHESS,
) -> models.Invitation:
    """
    Create a new invitation.

    Raises a sqlalchemy.exc.IntegrityError if from_id or to_id do not exist.
    Does not check if the from_id or to_id have been marked deleted, that will
    have to be done separately.
    """
    invitation = models.Invitation(from_id=from_id, to_id=to_id, game_type=game_type)
    session.add(invitation)
    await session.flush()
    await session.refresh(invitation)
    return invitation


async def get_invitations(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 10,
    order_by: str = "date_sent",
    reverse: bool = False,
    **kwargs,
) -> list[models.Invitation]:
    """
    Retrieve a list of invitations from DB.

    Examples:
        # get invitation by ID
        get_invitations(id_=10)

        # get pending invitations addressed to user with ID 3
        get_invitations(skip=0, limit=5, to_id=3, status='PENDING')
    """

    user_temp1 = aliased(models.User)
    user_temp2 = aliased(models.User)

    stmt = (
        select(
            models.Invitation,
            user_temp1.name.label("white_username"),
            user_temp2.name.label("black_username"),
        )
        .join(user_temp1, models.Invitation.to_id == user_temp1.id_)
        .join(user_temp2, models.Invitation.from_id == user_temp2.id_)
    )

    for k, v in kwargs.items():
        stmt = stmt.where(getattr(models.Invitation, k) == v)

    order_attr = getattr(models.Invitation, order_by)
    order_attr = order_attr.desc() if reverse else order_attr.asc()
    stmt = stmt.order_by(order_attr)

    stmt = stmt.offset(skip).limit(limit)

    rows = (await session.execute(stmt)).all()

    invitations: list[models.Invitation] = []

    for invitation, white_username, black_username in rows:
        invitation.white_username = white_username
        invitation.black_username = black_username
        invitations.append(invitation)

    return invitations


async def cancel_invitation(session: AsyncSession, id_: int) -> bool:
    """
    Cancel invitation.

    Returns False if invitation does not exist or does not have PENDING status.
    Returns True on success.
    """
    stmt = (
        update(models.Invitation)
        .where(
            models.Invitation.id_ == id_,
            models.Invitation.status == models.InvitationStatus.PENDING,
        )
        .values(status=models.InvitationStatus.CANCELLED)
    )
    result = await session.execute(stmt)
    return result.rowcount == 1  # pyright: ignore


async def accept_invitation(session: AsyncSession, id_: int) -> models.Game | None:
    """
    Accept pending invitation and create a new game.

    Randomly assigns players to team colors.

    Returns None if invitation does not exist or does not have PENDING status.
    Returns a new game object on success.
    """
    stmt = select(models.Invitation).where(
        models.Invitation.id_ == id_,
        models.Invitation.status == models.InvitationStatus.PENDING,
    )
    result = (await session.execute(stmt)).first()
    invitation = None if not result else result[0]
    if invitation is None:
        return None

    invitation.status = models.InvitationStatus.ACCEPTED
    invitation.date_answered = datetime.now()

    players = [invitation.from_id, invitation.to_id]
    random.shuffle(players)

    new_game = models.Game(
        white=players[0],
        black=players[1],
        whomst=players[0],
        invitation_id=id_,
        game_type=invitation.game_type,
    )
    session.add(new_game)
    await session.flush()
    await session.refresh(new_game)

    return new_game


async def decline_invitation(session: AsyncSession, id_: int) -> bool:
    """
    Decline pending invitation.

    Returns False if invitation does not exist or does not have PENDING status.
    Returns True on success.
    """
    stmt = (
        update(models.Invitation)
        .where(
            models.Invitation.id_ == id_,
            models.Invitation.status == models.InvitationStatus.PENDING,
        )
        .values(status=models.InvitationStatus.DECLINED, date_answered=datetime.now())
    )
    result = await session.execute(stmt)
    return result.rowcount == 1  # pyright: ignore


# pylint: disable=too-many-locals
async def get_games(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 10,
    order_by: str = "last_active",
    reverse: bool = False,
    **kwargs,
) -> list[models.Game]:
    """
    Retrieve a list of games from DB.

    Examples:
        # get game by ID
        get_games(id_=10)

        # list 10 games where white id = 5
        get_games(white=5, skip=0, limit=10)

    """

    user_temp1 = aliased(models.User)
    user_temp2 = aliased(models.User)

    stmt = (
        select(
            models.Game,
            user_temp1.name.label("white_username"),
            user_temp2.name.label("black_username"),
        )
        .join(user_temp1, models.Game.white == user_temp1.id_)
        .join(user_temp2, models.Game.black == user_temp2.id_)
    )

    # if player_id is included in request,
    # we want to query all games and return any where player_id == white or black
    if "player_id" in kwargs:
        player_id = kwargs.pop("player_id")
        stmt = stmt.where(
            or_(models.Game.white == player_id, models.Game.black == player_id)
        )

    for k, v in kwargs.items():
        stmt = stmt.where(getattr(models.Game, k) == v)

    order_by_attr = getattr(models.Game, order_by)
    stmt = stmt.order_by(order_by_attr.desc() if reverse else order_by_attr.asc())

    stmt = stmt.offset(skip).limit(limit)

    rows = (await session.execute(stmt)).all()

    games: list[models.Game] = []

    for game, white_username, black_username in rows:
        move_stmt = select(models.Move.movestr).where(models.Move.game_id == game.id_)
        move_hist = (await session.execute(move_stmt)).scalars().all()

        game.white_username = white_username
        game.black_username = black_username
        game.move_hist = move_hist

        games.append(game)

    return games

# pylint: disable=too-many-arguments
async def do_move(
    session: AsyncSession,
    id_: int,
    user_id: int,
    whomst: int,
    move: str,
    states: str,
    fen: str,
    status: str,
) -> models.Game:
    """updates game in database using given state"""

    new_move = models.Move(
        game_id=id_,
        user_id=user_id,
        movestr=move,
        fen=fen,
    )
    session.add(new_move)

    result = None
    winner = None

    if status in vars(models.GameResult):
        # throws value error if status not in GameResult
        result = status
        is_active = False

        if (
            status in models.GameResult.CHECKMATE
            or status in models.GameResult.RESIGNATION
            or status in models.GameResult.TIMEOUT
        ):
            winner = user_id

    else:
        # status is either MOVEOK or CHECK if its not in GameResult
        is_active = True

    stmt = (
        update(models.Game)
        .where(models.Game.id_ == id_)
        .values(
            states=states,
            fen=fen,
            is_active=is_active,
            result=result,
            last_active=datetime.now(),
            winner=winner,
            whomst=whomst,
        )
    )

    await session.execute(stmt)

    return (
        await session.execute(select(models.Game).where(models.Game.id_ == id_))
    ).one()[0]


async def forfeit(session: AsyncSession, id_: int, user_id: int) -> models.Game:
    """Forefeit game"""

    row = (await get_games(session, id_=id_))[0]
    game = row.game

    winner = game.white if user_id == game.black else game.black

    stmt = (
        update(models.Game)
        .where(models.Game.id_ == id_)
        .values(
            winner=winner,
            result=models.GameResult.RESIGNATION,
            is_active=False,
            last_active=datetime.now(),
        )
    )

    await session.execute(stmt)

    return (
        await session.execute(select(models.Game).where(models.Game.id_ == id_))
    ).one()[0]


async def create_challenge(
    session: AsyncSession,
    user_id: int,
    game_type: models.GameType = models.GameType.CHESS,
) -> models.ChallengeRequest:
    """Create challenge request"""
    challenge = models.ChallengeRequest(
        requester_id=user_id,
        game_type=game_type,
    )
    session.add(challenge)
    await session.flush()
    await session.refresh(challenge)
    return challenge


async def get_challenges(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 10,
    order_by: str = "created_at",
    reverse: bool = False,
    **kwargs,
) -> list[models.ChallengeRequest]:
    """Retrieve a list of challenge requests along with the requester's username"""

    requester = aliased(models.User)

    stmt = select(
        models.ChallengeRequest,
        requester.name.label("requester_username"),
    ).join(requester, models.ChallengeRequest.requester_id == requester.id_)

    for k, v in kwargs.items():
        stmt = stmt.where(getattr(models.ChallengeRequest, k) == v)

    order_attr = getattr(models.ChallengeRequest, order_by)
    order_attr = order_attr.desc() if reverse else order_attr.asc()
    stmt = stmt.order_by(order_attr)

    stmt = stmt.offset(skip).limit(limit)

    rows = (await session.execute(stmt)).all()

    challenges: list[models.ChallengeRequest] = []
    for challenge, requester_username in rows:
        challenge.requester_username = requester_username
        challenges.append(challenge)
    
    return challenges


async def accept_challenge(
    session: AsyncSession, id_: int, user_id: int
) -> models.Game | None:
    """Accept challenge request"""

    stmt = select(models.ChallengeRequest).where(
        models.ChallengeRequest.id_ == id_,
        models.ChallengeRequest.status == models.ChallengeRequestStatus.PENDING,
    )
    result = (await session.execute(stmt)).first()
    challenge = None if not result else result[0]
    if challenge is None:
        return None

    challenge.status = models.ChallengeRequestStatus.ACCEPTED
    challenge.fulfilled_by = user_id

    players = [challenge.requester_id, user_id]
    random.shuffle(players)

    new_game = models.Game(
        white=players[0],
        black=players[1],
        whomst=players[0],
        challenge_id=id_,
        game_type=challenge.game_type,
    )
    session.add(new_game)
    await session.flush()
    challenge.game_id = new_game.id_

    return new_game


async def cancel_challenge(session: AsyncSession, id_: int) -> bool:
    """
    Cancel challenge.

    Returns False if challenge does not exist.
    Returns True on success.
    """
    stmt = (
        update(models.ChallengeRequest)
        .where(
            models.ChallengeRequest.id_ == id_,
            models.ChallengeRequest.status == models.ChallengeRequestStatus.PENDING,
        )
        .values(status=models.ChallengeRequestStatus.CANCELLED)
    )
    result = await session.execute(stmt)
    return result.rowcount == 1  # pyright: ignore
