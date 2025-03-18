import os
from urllib.parse import quote

import redis.asyncio as redis
from dotenv import load_dotenv
from sqlmodel import Session, create_engine

load_dotenv()

DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = quote(os.getenv("DB_PASSWORD").encode())
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

DB_URL = f"mysql+pymysql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DB_URL)


def get_session():
    with Session(engine) as session:
        yield session


REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_DB = int(os.getenv("REDIS_DB", 0))


async def get_redis_client():
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        decode_responses=True,
    )
    try:
        yield redis_client
    finally:
        await redis_client.close()
