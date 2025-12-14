"""chessticulate.security"""

from typing import Annotated

import jwt
import pydantic
from fastapi import Depends, HTTPException
from fastapi.security.http import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from chessticulate_api import crud, db, schemas
from chessticulate_api.config import CONFIG


async def get_credentials(
    session: Annotated[AsyncSession, Depends(db.session)],
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(HTTPBearer())],
) -> schemas.Credentials:
    """Retrieve and validate user JWTs. For use in endpoints as dependency."""
    try:
        decoded_token = jwt.decode(
            credentials.credentials, CONFIG.jwt_secret, [CONFIG.jwt_algo]
        )
        result = schemas.Credentials(**decoded_token)
    except jwt.exceptions.DecodeError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc
    except jwt.exceptions.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="expired token") from exc
    except pydantic.ValidationError as exc:
        raise HTTPException(status_code=401, detail="JWT missing fields") from exc

    users = await crud.get_users(session, id_=decoded_token["user_id"])

    if not users or users[0].deleted:
        raise HTTPException(status_code=401, detail="user has been deleted")

    return result
