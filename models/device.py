from datetime import datetime
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class Base(SQLModel):
    name: str = Field(min_length=1, max_length=255, unique=True)
    location: str = Field(min_length=1, max_length=255)
    setup_id: int | None = Field(default=None, foreign_key="setup.id")


class Device(Base, table=True):
    id: int | None = Field(default=None, primary_key=True)
    last_seen: datetime
    # current_version: str : TODO
    api_key: str = Field(unique=True)
    # display_rotation : TODO
    # scheduled_playlist_id : TODO
    setup_id: int | None = Field(foreign_key="setup.id")
    # used_port we ommit it becouse we are using https on 443 : TODO

    setup: Optional["Setup"] = Relationship(back_populates="devices")


class DeviceInput(Base):
    code: int = Field(ge=100_000_000, le=999_999_999)


class DeviceUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    location: str | None = Field(default=None, min_length=1, max_length=255)
    # we need the setup id
    setup_id: int | None = Field(default=None, ge=1)


# Output models


class DevicePublicOutput(Base):
    id: int
    last_seen: datetime

    @classmethod
    def to_setup_model(cls, device: "DevicePublicOutput") -> "DeviceSetupOutput":
        return DeviceSetupOutput(
            id=device.id,
            data=f"{device.name} - {device.location}"
        )

class DeviceSetupOutput(SQLModel):
    id: int
    data: str

class DevicePrivateOutput(DevicePublicOutput):
    # used for device initial response when activated
    api_key: str

class DeviceOutput(SQLModel):
    # used for retriving info such as device name location if we gonna display them on the app client + inculded teh current setup to streamline the procces of fetching mutiple data for the device it self ( also used on device after receving isntruction to update it self such as new setup or setup update or removed )
    # we need the setup output here
    name: str = Field(min_length=1, max_length=255)
    location: str = Field(min_length=1, max_length=255)
    # we need setup it self can be null
    setup: Optional["SetupOutputUnderDevice"] = None
# Response models

from .setup import SetupOutputUnderDevice

class DeviceCodeOutput(SQLModel):
    code: int = Field(ge=100_000_000, le=999_999_999)


class DeleteDeviceResponse(SQLModel):
    detail: str

# extra models

class SnapshotInstructionInput(SQLModel):
    url: str = Field(min_length=1)