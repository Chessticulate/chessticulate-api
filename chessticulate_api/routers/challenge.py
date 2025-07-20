"""chessticulate_api.routers.challenge"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from chessticulate_api import crud, models, schemas, security

challenge_router = APIRouter(prefix="/challenges")


@challenge_router.post("", status_code=201)
async def create_challenge(
    credentials: Annotated[dict, Depends(security.get_credentials)],
    payload: schemas.CreateChallenegeRequestRequest,
) -> schemas.CreateInvitationResponse:
    """Create a new challenge request."""
    if credentials["user_id"] == payload.to_id:
        raise HTTPException(status_code=400, detail="cannot invite self")

    if not (users := await crud.get_users(id_=payload.to_id)):
        raise HTTPException(status_code=400, detail="addressee does not exist")

    if users[0].deleted:
        raise HTTPException(
            status_code=400, detail=f"user '{users[0].id_}' has been deleted"
        )

    result = await crud.create_invitation(credentials["user_id"], payload.to_id)
    return vars(result)

