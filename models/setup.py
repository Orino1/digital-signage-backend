from datetime import datetime, time

from sqlmodel import Field, Relationship, SQLModel

from .device import DevicePublicOutput, DeviceSetupOutput

from pydantic import field_validator


# Setup
class SetupBase(SQLModel):
    name: str = Field(min_length=1, max_length=256, unique=True)


class Setup(SetupBase, table=True):
    id: int | None = Field(default=None, primary_key=True)

    devices: list["Device"] = Relationship(back_populates="setup")
    data: list["Playlist"] = Relationship(
        back_populates="setup", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class SetupOutput(SetupBase):
    id: int
    devices: list[DeviceSetupOutput] = []
    data: list["PlaylistOutput"] = []
    # TODO: current playlist that is bieng played

class SetupOutputUnderDevice(SetupBase):
    id: int
    data: list["PlaylistOutput"] = []

class SetupInput(SetupBase):
    playlists: list["PlaylistInput"]
    devices: list[int] = []

    @field_validator("playlists")
    @classmethod
    def validate_non_empty(cls, v):
        if len(v) == 0:
            raise ValueError("playlists must not be empty")
        return v


class SetupUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    playlists_to_add: list["PlaylistInput"] = []
    playlists_to_update: list["PlaylistUpdate"] = []
    playlists_to_delete: list[int] = []
    devices_to_add: list[int] = []
    devices_to_remove: list[int] = []


# playlist
class PlaylistBase(SQLModel):
    name: str = Field(min_length=1, max_length=256)
    start_time: str = Field(min_length=5, max_length=5)
    end_time: str = Field(min_length=5, max_length=5)
    monday: bool
    tuesday: bool
    wednesday: bool
    thursday: bool
    friday: bool
    saturday: bool
    sunday: bool

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time(cls, value):
        try:
            time.fromisoformat(value)
            return value
        except ValueError:
            raise ValueError("Time must be in 'HH:MM' format")


class Playlist(PlaylistBase, table=True):
    id: int | None = Field(default=None, primary_key=True)

    setup_id: int = Field(foreign_key="setup.id")

    setup: Setup = Relationship(back_populates="data")
    images: list["Image"] = Relationship(
        back_populates="playlist",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    videos: list["Video"] = Relationship(
        back_populates="playlist",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class PlaylistInput(PlaylistBase):
    images: list["ImageBase"] = []
    videos: list[str] = []

class PlaylistOutput(PlaylistBase):
    id: int
    images: list["ImageOutput"] = []
    videos: list["VideoBase"] = []

class PlaylistUpdate(SQLModel):
    id: int
    name: str
    start_time: str = Field(min_length=5, max_length=5)
    end_time: str = Field(min_length=5, max_length=5)
    monday: bool
    tuesday: bool
    wednesday: bool
    thursday: bool
    friday: bool
    saturday: bool
    sunday: bool
    images_to_add: list["ImageBase"] = []
    images_to_delete: list[int] = []
    videos_to_add: list[str] = []
    videos_to_delete: list[int] = []

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time(cls, value):
        try:
            time.fromisoformat(value)
            return value
        except ValueError:
            raise ValueError("Time must be in 'HH:MM' format")
# images
class ImageBase(SQLModel):
    url: str = Field(min_length=1)
    duration: int = Field(ge=1)


class Image(ImageBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    playlist_id: int = Field(foreign_key="playlist.id")
    playlist: Playlist = Relationship(back_populates="images")    

class ImageOutput(ImageBase):
    id: int

# videos
class VideoBase(SQLModel):
    id: int | None = Field(default=None, primary_key=True)
    url: str = Field( min_length=1)


class Video(VideoBase, table=True):
    playlist_id: int = Field(foreign_key="playlist.id")
    playlist: Playlist = Relationship(back_populates="videos")


# extra mdoels

class S3PreSignedUrlOutput(SQLModel):
    upload_url: str = Field(min_length=1)
    file_url: str = Field(min_length=1)