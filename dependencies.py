from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt.exceptions import (DecodeError, ExpiredSignatureError,
                            InvalidTokenError)
from sqlmodel import Session

from .models import get_session
from .models.admin import Admin
from .models.device import Device
from .utils import ALGORITHM, KEY, TokenType

import redis.asyncio as redis

from fastapi.security.api_key import APIKeyHeader, APIKeyCookie

from sqlmodel import select


SessionDep = Annotated[Session, Depends(get_session)]
LoginFormDep = Annotated[OAuth2PasswordRequestForm, Depends()]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def validate_token(token: str) -> str:
    """
    Validate the signature of a token.

    Args:
        token (str): The token to be validated.

    Raises:
        HTTPException: If token invalid, expired or unable to decode it.

    Returns:
        string: subject of the decoded payload from the token.
    """
    try:
        payload = jwt.decode(token, f"{KEY}REFRESH", ALGORITHM)
        return payload["sub"]
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
        )
    except DecodeError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not decode token"
        )


def create_redis() -> redis.ConnectionPool:
    return redis.ConnectionPool(
        host='localhost', 
        port=6379, 
        db=0, 
        decode_responses=True
    )

pool = create_redis()

async def get_redis() -> redis.Redis:
  return redis.Redis(connection_pool=pool)

RedisDep = Annotated[redis.Redis, Depends(get_redis)]

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

def get_device_from_api_key(session: SessionDep, api_key: str = Depends(api_key_header)) -> Device:
    """Extract device model via provided api key"""
    device = session.exec(select(Device).filter_by(api_key=api_key)).first()

    if not device:
        raise HTTPException(detail="Api key not valid", status_code=status.HTTP_401_UNAUTHORIZED)

    return device

DeviceKeyDep = Annotated[Device, Depends(get_device_from_api_key)]

api_key_cookie = APIKeyCookie(name="TOKEN", auto_error=True)
def get_admin_from_cookie_key(session: SessionDep, token: str = Depends(api_key_cookie)) -> Admin:
    """Validate token from cookie and extract admiin model"""
    admin = session.exec(select(Admin).filter_by(id=int(validate_token(token)))).first()

    if not admin:
        raise HTTPException(detail="Admin not found", status_code=status.HTTP_404_NOT_FOUND)

    return admin

AdminKeyDep = Annotated[Admin, Depends(get_admin_from_cookie_key)]