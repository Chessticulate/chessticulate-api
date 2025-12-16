"""chessticulate_api.routers.challenge"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from chessticulate_api import crud, db, models, schemas, security

challenge_router = APIRouter(prefix="/challenges")


@challenge_router.post("", status_code=201)
async def create_challenge(
    session: Annotated[AsyncSession, Depends(db.session)],
    credentials: Annotated[schemas.Credentials, Depends(security.get_credentials)],
) -> schemas.CreateChallengeResponse:
    """Create a new challenge request"""

    async with session.begin():
        if not (
            await crud.get_challenges(
                session,
                requester_id=credentials.user_id,
                status=models.ChallengeRequestStatus.PENDING,
            )
        ):
            raise HTTPException(
                status_code=409, detail="user already has pending challenge request"
            )
        challenge = await crud.create_challenge(session, credentials.user_id)
    return schemas.CreateChallengeResponse(**vars(challenge))


# pylint: disable=too-many-arguments
@challenge_router.get("")
async def get_challenges(
    session: Annotated[AsyncSession, Depends(db.session)],
    _: Annotated[schemas.Credentials, Depends(security.get_credentials)],
    requester_id: int | None = None,
    responder_id: int | None = None,
    challenge_id: int | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: Annotated[int, Field(gt=0, le=50)] = 10,
    reverse: bool = False,
) -> list[schemas.GetChallengeResponse]:
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
    challenges = await crud.get_challenges(
        session, **args, status=models.ChallengeRequestStatus.PENDING
    )

    result = [
        schemas.GetChallengeResponse(
            **vars(challenge_data[0]),
            requester_username=challenge_data[1],
        )
        for challenge_data in challenges
    ]

    return result


@challenge_router.post("/{challenge_id}/accept", status_code=202)
async def accept_challenge(
    session: Annotated[AsyncSession, Depends(db.session)],
    credentials: Annotated[schemas.Credentials, Depends(security.get_credentials)],
    challenge_id: int,
) -> schemas.AcceptChallengeResponse:
    """Accept a challenge request"""

    async with session.begin():
        # does challenge exist
        challenge_list = await crud.get_challenges(
            session,
            id_=challenge_id,
            limit=1,
            status=models.ChallengeRequestStatus.PENDING,
        )
        if not challenge_list:
            raise HTTPException(status_code=404, detail="challenge does not exist")

        challenge, _ = challenge_list[0]

        # is this a user accepting own challenge
        if credentials.user_id == challenge.requester_id:
            raise HTTPException(status_code=400, detail="cannot accept own challenge")

        # does creator still exist
        user = await crud.get_users(session, id_=challenge.requester_id)
        if user[0].deleted:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"user with ID '{challenge.requester_id}' who made challenge with id"
                    f" '{challenge_id}' does not exist"
                ),
            )

        if not (
            result := await crud.accept_challenge(
                session, challenge_id, credentials.user_id
            )
        ):
            # challenge was accepted while we were processing this request
            raise HTTPException(
                status_code=404, detail="sorry, this challenge is no longer available"
            )

    return schemas.AcceptChallengeResponse(game_id=result.id_)


@challenge_router.post("/{challenge_id}/cancel", status_code=200)
async def cancel_challenge(
    session: Annotated[AsyncSession, Depends(db.session)],
    credentials: Annotated[schemas.Credentials, Depends(security.get_credentials)],
    challenge_id: int,
):
    """Cancel a challenge request"""

    async with session.begin():
        challenge_list = await crud.get_challenges(
            session, id_=challenge_id, status=models.ChallengeRequestStatus.PENDING
        )

        # does challenge exist
        if not challenge_list:
            raise HTTPException(status_code=404, detail="challenge does not exist")

        challenge, _ = challenge_list[0]

        # only the creator can cancel the challenge
        if credentials.user_id != challenge.requester_id:
            raise HTTPException(
                status_code=403, detail="can't cancel someone else's challenge"
            )

        if not await crud.cancel_challenge(session, challenge_id):
            raise HTTPException(status_code=500)
