"""chessticulate_api.routers.game"""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from chessticulate_api import crud, schemas, security, workers_service

game_router = APIRouter(prefix="/games")


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
    if is_active:
        args["is_active"] = is_active
    games = await crud.get_games(**args)

    result = [
        {
            **vars(game_data["game"]),
            "white_username": game_data["white_username"],
            "black_username": game_data["black_username"],
        }
        for game_data in games
    ]

    return result


@game_router.post("/{game_id}/move")
async def move(
    credentials: Annotated[dict, Depends(security.get_credentials)],
    game_id: str,
    payload: schemas.DoMoveRequest,
) -> schemas.DoMoveResponse:
    """Attempt a move on a given game"""

    user_id = credentials["user_id"]
    games = await crud.get_games(id_=int(game_id))

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
    updated_game = await crud.do_move(
        game_id,
        user_id,
        payload.move,
        json.dumps(states),
        fen,
        status,
    )

    return vars(updated_game)


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
