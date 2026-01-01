"""chessticulate_api.routers.game"""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from chessticulate_api import crud, db, schemas, security, workers_service

game_router = APIRouter(prefix="/games")


# pylint: disable=too-many-arguments, disable=too-many-positional-arguments
@game_router.get("")
async def get_games(
    session: Annotated[AsyncSession, Depends(db.session)],
    _: Annotated[schemas.Credentials, Depends(security.get_credentials)],
    game_id: int | None = None,
    player_id: int | None = None,
    invitation_id: int | None = None,
    white_id: int | None = None,
    black_id: int | None = None,
    whomst_id: int | None = None,
    winner_id: int | None = None,
    is_active: bool | None = None,
    skip: int = 0,
    limit: Annotated[int, Field(gt=0, le=50)] = 10,
    reverse: bool = False,
) -> list[schemas.GetGameResponse]:
    """Retrieve a list of games"""
    args = {"skip": skip, "limit": limit, "reverse": reverse}

    if game_id:
        args["id_"] = game_id
    if invitation_id:
        args["invitation_id"] = invitation_id
    if white_id:
        args["white"] = white_id
    if black_id:
        args["black"] = black_id
    if whomst_id:
        args["whomst"] = whomst_id
    if winner_id:
        args["winner"] = winner_id
    if player_id:
        args["player_id"] = player_id
    if is_active is not None:
        args["is_active"] = is_active
    games = await crud.get_games(session, **args)

    result = [schemas.GetGameResponse(**vars(game)) for game in games]

    return result


# pylint: disable=too-many-locals
@game_router.post("/{game_id}/move")
async def move(
    session: Annotated[AsyncSession, Depends(db.session)],
    request: Request,
    credentials: Annotated[schemas.Credentials, Depends(security.get_credentials)],
    game_id: int,
    payload: schemas.DoMoveRequest,
) -> schemas.DoMoveResponse:
    """Attempt a move on a given game"""

    user_id = credentials.user_id
    games = await crud.get_games(session, id_=game_id)

    if not games:
        raise HTTPException(status_code=404, detail="invalid game id")

    game = games[0]

    if user_id not in [game.white, game.black]:
        raise HTTPException(
            status_code=403,
            detail=f"user '{user_id}' not a player in game '{game_id}'",
        )

    if user_id != game.whomst:
        raise HTTPException(
            status_code=400,
            detail=f"it is not the turn of user with id '{user_id}'",
        )

    try:
        response = await workers_service.do_move(
            game.fen, payload.move, json.loads(game.states)
        )
    except workers_service.ClientRequestError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except workers_service.ServerRequestError as e:
        raise HTTPException(status_code=500) from e

    status = response["status"]
    states = response["states"]
    fen = response["fen"]
    whomst = game.white if game.whomst == game.black else game.black

    updated_game = await crud.do_move(
        session,
        game_id,
        user_id,
        whomst,
        payload.move,
        json.dumps(states),
        fen,
        status,
    )

    # publish update to redis
    redis: Redis = request.app.state.redis
    event = {
        "type": "move",
        "gameId": game_id,
        "move": payload.move,
        "fen": fen,
        "status": status,
        "whomst": whomst,
    }
    await redis.publish(f"game:{game_id}", json.dumps(event))

    return schemas.DoMoveResponse(**vars(updated_game))


# whenever a move is performed, this function is called
# the front end will hit this "long get" and once it has it will recieve game updates
@game_router.get("/{game_id}/update")
async def game_update(
    _: Annotated[schemas.Credentials, Depends(security.get_credentials)],
    request: Request,
    game_id: int,
) -> StreamingResponse:
    """subscribe to recieve live updates from games"""

    redis: Redis = request.app.state.redis
    pubsub = redis.pubsub()
    channel = f"game:{game_id}"
    await pubsub.subscribe(channel)

    async def event_stream():
        # notify client that connection has been made
        yield ": connected\n\n"
        try:
            while True:
                # wait 1s for message, send heartbeat if none
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if msg and msg["type"] == "message":
                    data = msg["data"]
                    yield f"data: {data}\n\n"
                else:
                    yield ": ping\n\n"
                if await request.is_disconnected():
                    break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
    }
    return StreamingResponse(event_stream(), headers=headers)


@game_router.post("/{game_id}/forfeit")
async def forfeit(
    session: Annotated[AsyncSession, Depends(db.session)],
    credentials: Annotated[schemas.Credentials, Depends(security.get_credentials)],
    game_id: int,
) -> schemas.ForfeitResponse:
    """Forfeit a given game"""

    user_id = credentials.user_id
    games = await crud.get_games(session, id_=game_id, lock_rows=True)

    if not games:
        raise HTTPException(status_code=404, detail="invalid game id")

    game = games[0]

    if user_id not in [game.white, game.black]:
        raise HTTPException(
            status_code=403,
            detail=f"user '{user_id}' not a player in game '{game_id}'",
        )

    quiter = await crud.forfeit(session, user_id, game)

    return schemas.ForfeitResponse(**vars(quiter))
