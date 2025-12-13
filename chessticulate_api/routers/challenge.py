"""chessticulate_api.routers.challenge"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from chessticulate_api import crud, models, schemas, security

challenge_router = APIRouter(prefix="/challenges")


# pylint: disable=unused-argument
@challenge_router.post("", status_code=201)
async def create_challenge(
    credentials: Annotated[dict, Depends(security.get_credentials)],
) -> (
    schemas.CreateChallengeResponse
):
    """Create a new challenge request"""

    challenge = await crud.create_challenge(credentials["user_id"])
    return vars(challenge)


# pylint: disable=too-many-arguments. too-many-positional-arguments
@challenge_router.get("")
async def get_challenges(
    credentials: Annotated[dict, Depends(security.get_credentials)],
    requester_id: int | None = None,
    responder_id: int | None = None,
    challenge_id: int | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: Annotated[int, Field(gt=0, le=50)] = 10,
    reverse: bool = False,
) -> schemas.GetChallengeListResponse:
    """Retrieve challenges"""

    args = {"skip": skip, "limit": limit, "reverse": reverse}

    if requester_id:
        args["requester_id"] = requester_id
    if responder_id:
        args["fulfilled_by"] = responder_id
    if challenge_id:
        args["id_"] = challenge_id
    if status:
        args["status"] = status
    challenges = await crud.get_challenges(**args)

    result = [
        {
            **vars(challenge_data["challenge"]),
            "requester_username": challenge_data["requester_username"],
        }
        for challenge_data in challenges
    ]

    return result


@challenge_router.post("/{challenge_id}/accept", status_code=202)
async def accept_challenge(
    credentials: Annotated[dict, Depends(security.get_credentials)],
    challenge_id: int,
) -> schemas.AcceptChallengeResponse:
    """Accept a challenge request"""

    # does challenge exist
    challenge_list = await crud.get_challenges(id_=challenge_id, limit=1)
    if not challenge_list:
        raise HTTPException(status_code=400, detail="challenge does not exist")

    challenge = challenge_list[0]["challenge"]

    # is this a user accepting own challenge
    if credentials["user_id"] == challenge.requester_id:
        raise HTTPException(status_code=400, detail="cannot accept own challenge")

    # does creator still exist
    user = await crud.get_users(id_=challenge.requester_id)
    if user[0].deleted:
        raise HTTPException(
            status_code=404,
            detail=(
                f"user with ID '{challenge.requester_id}' who created challenge with id"
                f" '{challenge_id}' does not exist"
            ),
        )

    user_id = credentials["user_id"]
    if not (result := await crud.accept_challenge(challenge_id, user_id)):
        # possible race condition
        raise HTTPException(status_code=500)

    return {"game_id": result.id_}


@challenge_router.post("/{challenge_id}/cancel", status_code=200)
async def cancel_challenge(
    credentials: Annotated[dict, Depends(security.get_credentials)],
    challenge_id: int,
):
    """Cancel a challenge request"""

    challenge_list = await crud.get_challenges(id_=challenge_id)

    # does challenge exist
    if not challenge_list:
        raise HTTPException(status_code=400, detail="challenge does not exist")

    challenge = challenge_list[0]["challenge"]

    # only the creator can cancel the challenge
    if credentials["user_id"] != challenge.requester_id:
        raise HTTPException(
            status_code=403, detail="can't cancel someone else's challenge"
        )

    # if challenge isn't pending, it cannot be canceled
    if challenge.status != models.ChallengeRequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="challenge is no longer pending")

    if not await crud.cancel_challenge(challenge_id):
        raise HTTPException(status_code=500)
