from sqlmodel import Field, SQLModel


class Base(SQLModel):
    username: str = Field(..., min_length=1, max_length=255, unique=True)


class Admin(Base, table=True):
    id: int | None = Field(default=None, primary_key=True)
    password: str


class AdminInput(Base):
    password: str = Field(..., min_length=8, max_length=38)


class AdminUpdate(SQLModel):
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=38)


class AdminOutput(Base):
    id: int
