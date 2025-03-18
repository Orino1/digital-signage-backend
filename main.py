import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import lifespan
from .routers import device, setup, code, admin

app = FastAPI(lifespan=lifespan)

cors_origins = os.getenv("CORS_ORIGINS").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(device.router, prefix="/devices")
app.include_router(code.router, prefix="/codes")
app.include_router(setup.router, prefix="/setups")
app.include_router(admin.router, prefix="/admins")


@app.get("/")
def read_root():
    return {"msg": "You found the root :)."}