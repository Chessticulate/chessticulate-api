from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security.http import HTTPAuthorizationCredentials, HTTPBearer

from chessticulate_api import crud
from chessticulate_api.routers.v1 import schemas

router = APIRouter()

security = HTTPBearer()


def get_credentials(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]
) -> dict:
    try:
        decoded_token = crud.validate_token(credentials.credentials)
    except jwt.exceptions.DecodeError:
        raise HTTPException(status_code=401, detail="invalid token")
    except jwt.exceptions.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="expired token")
    return decoded_token


@router.post("/login")
async def login(name: str, pswd: str) -> schemas.LoginResponse:
    return await crud.login(name, pswd)


@router.post("/signup")
async def signup(payload: schemas.CreateUserRequest) -> schemas.CreateUserResponse:
    return dict(
        await crud.create_user(payload.name, payload.email, SecretStr(payload.password))
    )


@router.get("/user")
async def get_user(
    credentials: Annotated[dict, Depends(get_credentials)],
    user_id: int | None = None,
    user_name: str | None = None,
) -> schemas.GetUserResponse:
    if user_id:
        return dict(await crud.get_user_by_id(user_id))
    if user_name:
        return dict(await crud.get_user_by_name(user_name))

    raise HTTPException(
        status_code=400, detail="must provide either 'user_id' or 'user_name'"
    )


@router.post("/invitation")
async def create_invitation(
    credentials: Annotated[dict, Depends(get_credentials)],
    payload: schemas.CreateInvitationRequest,
) -> schemas.CreateInvitationResponse:
    return dict(await crud.create_invitation(credentials["user_id"], payload.to))


@router.get("/invitations")
async def get_invitations(
        credentials: Annotated[dict, Depends(get_credentials)], 
        to_id: int,
        from_id: int,
        invitation_id: int | None = None,
        status: str | None = None,
        skip: int | None = 10,
        limit: int | None = 1) -> schemas.GetInvitationResponse:

    if from_id != credentials["user_id"] and to_id != credentials["user_id"]
        raise HTTPException(status_code=400, detail="requestor id must match either 'from_id' or 'to_id'")           

    args = {
        "to_id": to_id,
        "from_id": from_id,
        "skip": skip,
        "limit": limit
    }
    if invitation_id: 
        args["invitation_id"] = invitation_id
    if status:
        args["status"] = status
    result = await crud.get_invitations(**args)
   
    return [dict(inv) for inv in result]



@router.post("/invitations/{invitation_id}/accept")
async def accept_invitation(credentials: Annotated[dict, Depends(get_credentials)], invitation_id: int) -> schemas.AcceptInvitationResponse
    
