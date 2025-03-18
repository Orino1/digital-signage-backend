import os
from datetime import datetime, timedelta
from enum import Enum

import jwt
from passlib.context import CryptContext

import secrets

import boto3

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


KEY: str = os.getenv("JWT_SECRET_KEY")
ACCESS_EXPIRE: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES"))
REFRESH_EXPIRE: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES"))
ALGORITHM: str = os.getenv("JWT_ALGORITHM")


class TokenType(Enum):
    """Enumeration for token types"""

    ACCESS: str = "access"
    REFRESH: str = "refresh"


def create_token(subject: str | int, token_type: TokenType) -> str:
    """Create a JWT token : Access | Refresh"""
    now = datetime.now()
    payload = {
        "sub": str(subject),
        "exp": (
            now + timedelta(minutes=ACCESS_EXPIRE)
            if token_type == TokenType.ACCESS
            else now + timedelta(days=REFRESH_EXPIRE)
        ),
    }
    secret_key = KEY if token_type == TokenType.ACCESS else KEY + "REFRESH"
    token = jwt.encode(payload, secret_key, ALGORITHM)

    return token

def generate_api_key():
    """Generate an api key using token_urlsafe"""
    return secrets.token_urlsafe(32)

def get_s3_client():
    """Generate s3 client"""
    return boto3.client(
        's3',
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION")
    )