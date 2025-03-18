from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import SQLModel

from .models import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .models.device import Device
    from .models.setup import Setup
    from .models.admin import Admin


    #SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    # TODO: edit on prod
    from .models import Session
    from .utils import pwd_context
    from sqlmodel import select



    def create_admin_if_none():
        with Session(engine) as session:
            root_admin = session.exec(select(Admin).filter_by(username="root")).first()
            if not root_admin:
                password = "Qwerty123"
                hashed_pass = pwd_context.hash(password)
                session.add(Admin(username="root", password=hashed_pass))
                session.commit()

    
    create_admin_if_none()


    yield

    #SQLModel.metadata.drop_all(engine)
