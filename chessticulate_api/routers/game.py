"""chessticulate_api.routers.game"""

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from chessticulate_api import crud, schemas, security, workers_service

game_router = APIRouter(prefix="/games")

# SUBS: game_id -> set of per-connection queues (one queue per SSE connection)
SUBS: dict[int, set[asyncio.Queue[str]]] = {}

def subs(game_id: int) -> set[asyncio.Queue[str]]:
    return SUBS.setdefault(game_id, set())


# Async generator used by the SSE endpoint
async def game_stream(request: Request, game_id: int, q: asyncio.Queue[str]):
    yield ": connected\n\n"
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=20.0)
                yield f"data: {msg}\n\n"
            except asyncio.TimeoutError:
                # heartbeat to keep proxies from closing the connection
                yield ": ping\n\n"

            if await request.is_disconnected():
                break
    finally:
        s = SUBS.get(game_id)
        if s:
            s.discard(q)
            if not s:
                SUBS.pop(game_id, None)


# pylint: disable=too-many-arguments, too-many-positional-arguments
@game_router.get("")
async def get_games(
    # pylint: disable=unused-argument
    credentials: Annotated[dict, Depends(security.get_credentials)],
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
) -> schemas.GetGamesListResponse:
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
    games = await crud.get_games(**args)

    result = [
        {
            **vars(game_data["game"]),
            "white_username": game_data["white_username"],
            "black_username": game_data["black_username"],
            "move_hist": game_data["move_hist"],
        }
        for game_data in games
    ]

    return result


@game_router.post("/{game_id}/move")
async def move(
    credentials: Annotated[dict, Depends(security.get_credentials)],
    game_id: int,
    payload: schemas.DoMoveRequest,
) -> schemas.DoMoveResponse:
    """Attempt a move on a given game"""

    user_id = credentials["user_id"]
    games = await crud.get_games(id_=game_id)

    if not games:
        raise HTTPException(status_code=404, detail="invalid game id")

    game = games[0]["game"]

    if user_id not in [game.white, game.black]:
        raise HTTPException(
            status_code=403, detail=f"user '{user_id}' not a player in game '{game_id}'"
        )

    if user_id != game.whomst:
        raise HTTPException(
            status_code=400, detail=f"it is not the turn of user with id '{user_id}'"
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
        game_id,
        user_id,
        whomst,
        payload.move,
        json.dumps(states),
        fen,
        status,
    )
    
    # Broadcast to subscribers if any
    event = json.dumps({
        "type": "move",
        "gameId": game_id,
        "move": payload.move,
        "fen": fen,
        "status": status,
        "whomst": whomst,
    })
    for q in list(SUBS.get(game_id, ())):
        asyncio.create_task(q.put(event))

    return vars(updated_game)


# whenever a move is performed, this function is called
# the front end will hit this "long get" and once it has it will recieve game updates
@game_router.get("/{game_id}/update")
async def game_update(request: Request, game_id: int) -> schemas.GameUpdateResponse:
    """recieve live updates from games"""

    q: asyncio.Queue[str] = asyncio.Queue()
    s = subs(game_id)
    s.add(q)

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
    }
    return StreamingResponse(game_stream(request, game_id, q), headers=headers)

@game_router.post("/{game_id}/forfeit")
async def forfeit(
    credentials: Annotated[dict, Depends(security.get_credentials)], game_id: int
) -> schemas.ForfeitResponse:
    """Forfeit a given game"""

    user_id = credentials["user_id"]
    games = await crud.get_games(id_=game_id)

    if not games:
        raise HTTPException(status_code=404, detail="invalid game id")

    game = games[0]["game"]

    if user_id not in [game.white, game.black]:
        raise HTTPException(
            status_code=403, detail=f"user '{user_id}' not a player in game '{game_id}'"
        )

    quiter = await crud.forfeit(game_id, user_id)

    return vars(quiter)
