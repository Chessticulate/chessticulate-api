"""chessticulate_api.crud"""

import random
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from pydantic import SecretStr
from sqlalchemy import or_, select, update
from sqlalchemy.orm import aliased

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


async def get_users(
    *,
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


async def login(name: str, submitted_pswd: SecretStr) -> str | None:
    """
    Validate user name and password.

    Returns None if login fails.
    Returns JWT in the form of a str on success.
    """
    result = await get_users(name=name, deleted=False)
    if len(result) == 0:
        return None
    user = result[0]

    if not _check_password(submitted_pswd, user.password):
        return None
    return jwt.encode(
        {
            "exp": datetime.now(tz=timezone.utc) + timedelta(days=CONFIG.jwt_ttl),
            "user_name": user.name,
            "user_id": user.id_,
        },
        CONFIG.jwt_secret,
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
) -> list[tuple[models.Invitation, str, str]]:
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

    async with db.async_session() as session:

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

        if reverse:
            stmt = stmt.order_by(models.Invitation.date_sent.desc())
        else:
            stmt = stmt.order_by(models.Invitation.date_sent.asc())

        stmt = stmt.offset(skip).limit(limit)

        result = (await session.execute(stmt)).all()

        return [
            {
                "invitation": invitation,
                "white_username": white_username,
                "black_username": black_username,
            }
            for invitation, white_username, black_username in result
        ]


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

    Randomly assigns players to team colors.

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
            .values(
                status=models.InvitationStatus.DECLINED, date_answered=datetime.now()
            )
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount == 1


# pylint: disable=too-many-locals
async def get_games(
    *,
    skip: int = 0,
    limit: int = 10,
    order_by: str = "last_active",
    reverse: bool = False,
    **kwargs,
) -> list[tuple[models.Game, str, str]]:
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

    async with db.async_session() as session:
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
        if reverse:
            order_by_attr = order_by_attr.desc()
        else:
            order_by_attr = order_by_attr.asc()
        stmt = stmt.order_by(order_by_attr)

        stmt = stmt.offset(skip).limit(limit)

        result = (await session.execute(stmt)).all()

        games = [
            {
                "game": game,
                "white_username": white_username,
                "black_username": black_username,
            }
            for game, white_username, black_username in result
        ]

        # Fetch moves separately
        for g in games:
            move_stmt = select(models.Move.movestr).where(
                models.Move.game_id == g["game"].id_
            )
            moves = (await session.execute(move_stmt)).scalars().all()
            g["move_hist"] = moves

        return games


# pylint: disable=too-many-arguments, too-many-positional-arguments
async def do_move(
    id_: int,
    user_id: int,
    whomst: int,
    move: str,
    states: str,
    fen: str,
    status: str,
) -> models.Game:
    """updates game in database using given state"""

    async with db.async_session() as session:

        new_move = models.Move(
            game_id=id_,
            user_id=user_id,
            movestr=move,
            fen=fen,
        )
        session.add(new_move)

        result = None
        winner = None

        # pylint: disable=consider-using-in
        if status in vars(models.GameResult):
            # throws value error if status not in GameResult
            result = status
            is_active = False

            if (
                status == models.GameResult.CHECKMATE
                or status == models.GameResult.RESIGNATION
                or status == models.GameResult.TIMEOUT
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
        await session.commit()

        return (
            await session.execute(select(models.Game).where(models.Game.id_ == id_))
        ).one()[0]


async def get_moves(
    *, skip: int = 0, limit: int = 10, reverse: bool = False, **kwargs
) -> list[models.Move]:
    """Get move(s) from database"""

    async with db.async_session() as session:
        stmt = select(models.Move)
        for k, v in kwargs.items():
            stmt = stmt.where(getattr(models.Move, k) == v)

        if reverse:
            stmt = stmt.order_by(models.Move.timestamp.desc())
        else:
            stmt = stmt.order_by(models.Move.timestamp.asc())

        stmt = stmt.offset(skip).limit(limit)
        return [row[0] for row in (await session.execute(stmt)).all()]


async def forfeit(id_: int, user_id: int) -> models.Game:
    """Forefeit game"""

    async with db.async_session() as session:
        game_list = await get_games(id_=id_)
        game = game_list[0]["game"]
        winner = game.white if user_id == game.black else game.black

        stmt = (
            update(models.Game)
            .where(models.Game.id_ == id_)
            .values(
                winner=winner,
                result="RESIGNATION",
                is_active=False,
                last_active=datetime.now(),
            )
        )

        await session.execute(stmt)
        await session.commit()

        # maybe this should return a call to get_games
        # so usernames are included in response
        return (
            await session.execute(select(models.Game).where(models.Game.id_ == id_))
        ).one()[0]
