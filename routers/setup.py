import os
import uuid

from botocore.exceptions import NoCredentialsError
from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from ..dependencies import SessionDep, RedisDep, AdminKeyDep
from ..models.device import Device, DevicePublicOutput
from ..models.setup import (
    Image,
    Playlist,
    S3PreSignedUrlOutput,
    Setup,
    SetupInput,
    SetupOutput,
    SetupUpdate,
    Video,
)
from ..utils import get_s3_client

from datetime import datetime

import json

router = APIRouter()


@router.get("/", response_model=list[SetupOutput],     summary="Retrieve a list of all setups.",
    description="Fetches and returns a list of all setup configurations stored in the database.",
    tags=["Setups"])
def get_setups_info(session: SessionDep, admin: AdminKeyDep) -> list[SetupOutput]:
    setups = session.exec(select(Setup)).all()

    setups_structure = [SetupOutput(
        name=setup.name,
        id=setup.id,
        devices=[DevicePublicOutput.to_setup_model(device) for device in setup.devices],
        data=setup.data,
    ) for setup in setups]


    return setups_structure


@router.get("/{setup_id}", response_model=SetupOutput, summary="Retrieve detailed information for a specific setup.",
    description="Retrieves and returns the detailed information for a setup identified by `setup_id`. Includes associated devices and playlist details.",
    tags=["Setups"])
async def get_setup_info(setup_id: int, session: SessionDep, admin: AdminKeyDep) -> SetupOutput:
    setup = session.exec(select(Setup).filter_by(id=setup_id)).first()
    if not setup:
        raise HTTPException(
            detail=f"Setup {setup_id} not dound", status_code=status.HTTP_404_NOT_FOUND
        )

    setup_structure = SetupOutput(
        name=setup.name,
        id=setup.id,
        devices=[DevicePublicOutput.to_setup_model(device) for device in setup.devices],
        data=setup.data,
    )
    return setup_structure


@router.post("/", response_model=SetupOutput, summary="Create a new setup configuration.",
    description="Creates a new setup configuration with provided details, including playlists and device associations. Upon successful creation, it sends an `update_setup` instruction to all associated devices via Redis pub/sub. Devices listening on `/device/me/instructions` will receive this instruction and subsequently fetch updated setup information from `/device/me`.",
    tags=["Setups"],
    responses={
        200: {
            "description": "Setup created successfully.",
            "content": {"application/json": {"example": {"id": 1, "name": "Example Setup"}}},
        },
    })
async def create_setup(data: SetupInput, session: SessionDep, redis: RedisDep, admin: AdminKeyDep) -> SetupOutput:
    name_exists = session.exec(select(Setup).filter_by(name=data.name)).first()

    # unqiue name for setup
    if name_exists:
        raise HTTPException(
            detail=f"Name {data.name} already in use.",
            status_code=status.HTTP_409_CONFLICT,
        )
    # unqiue name for playlists
    playlist_names = [playlist.name for playlist in data.playlists]
    if len(playlist_names) != len(set(playlist_names)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Playlist name must be unqiue within a setip",
        )

    try:
        days = [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ]
        for day in days:
            # TODO: Ai generated make your own
            # Filter playlists that run on this specific day
            day_playlists = [p for p in data.playlists if getattr(p, day)]

            # Sort by start_time
            day_playlists.sort(key=lambda p: datetime.strptime(p.start_time, "%H:%M"))

            # Compare each playlist with the next one
            for i in range(len(day_playlists) - 1):
                current_end = datetime.strptime(day_playlists[i].end_time, "%H:%M")
                next_start = datetime.strptime(day_playlists[i + 1].start_time, "%H:%M")
                if current_end > next_start:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Playlists '{day_playlists[i].name}' and '{day_playlists[i + 1].name}' overlap on {day}",
                    )

        new_setup = Setup(name=data.name)

        session.add(new_setup)
        session.flush()

        # add playlists
        for playlist_data in data.playlists:
            if len(playlist_data.images) == 0 and len(playlist_data.videos) == 0:
                raise HTTPException(detail=f"Playlist {playlist_data.name} must have at least one image or video", status_code=status.HTTP_400_BAD_REQUEST)

            start_time = datetime.strptime(playlist_data.start_time, "%H:%M")
            end_time = datetime.strptime(playlist_data.end_time, "%H:%M")

            if start_time >= end_time:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Playlist {playlist_data.name} start_time must be before end_time",
                )

            new_playlist = Playlist(
                name=playlist_data.name,
                start_time=playlist_data.start_time,
                end_time=playlist_data.end_time,
                monday=playlist_data.monday,
                tuesday=playlist_data.tuesday,
                wednesday=playlist_data.wednesday,
                thursday=playlist_data.thursday,
                friday=playlist_data.friday,
                saturday=playlist_data.saturday,
                sunday=playlist_data.sunday,
                setup_id=new_setup.id,
            )
            session.add(new_playlist)
            session.flush()

            # add images
            for image in playlist_data.images:
                new_image = Image(
                    url=image.url, duration=image.duration, playlist_id=new_playlist.id
                )
                session.add(new_image)

            # add vidoes
            for video_url in playlist_data.videos:
                new_video = Video(url=video_url, playlist_id=new_playlist.id)
                session.add(new_video)

        # link devices with setup
        for device_id in data.devices:
            device = session.exec(select(Device).filter_by(id=device_id)).first()
            if not device:
                raise HTTPException(
                    detail=f"Device with id {device_id} not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            device.setup_id = new_setup.id
            session.add(device)

        session.commit()

        # notify linked devices with instruction of update setup
        for device_id in data.devices:
            instruction = json.dumps({"instruction": "update_setup"})
            await redis.publish(f"device:{device.id}:instructions", instruction)

        new_setup_structure = SetupOutput(
            name=new_setup.name,
            id=new_setup.id,
            devices=[
                DevicePublicOutput.to_setup_model(device)
                for device in new_setup.devices
            ],
            data=new_setup.data,
        )
        return new_setup_structure
    except HTTPException as e:
        session.rollback()
        raise
    except Exception as e:
        session.rollback()
        raise


@router.delete("/{setup_id}", summary="Delete a setup configuration.",
    description="Deletes a setup configuration identified by `setup_id`. After deletion, it sends an `update_setup` instruction to all associated devices via Redis pub/sub. Devices listening on `/device/me/instructions` will receive this instruction and subsequently fetch updated setup information from `/device/me`.",
    tags=["Setups"],
    responses={
        200: {
            "description": "Setup deleted successfully.",
            "content": {"application/json": {"example": {"detail": "Setup 1 deleted successfully."}}},
        },
    })
async def delete_setup(setup_id: int, session: SessionDep, redis: RedisDep, admin: AdminKeyDep):
    setup = session.exec(select(Setup).filter_by(id=setup_id)).first()
    if not setup:
        raise HTTPException(
            detail=f"Setup {setup_id} not dound", status_code=status.HTTP_404_NOT_FOUND
        )

    # notify linked devices with instruction of update setup
    for linked_device in setup.devices:
        instruction = json.dumps({"instruction": "update_setup"})
        await redis.publish(f"device:{linked_device.id}:instructions", instruction)
    session.delete(setup)
    session.commit()

    return {"detail": f"Setup {setup_id} deleted successfully."}


@router.put("/{setup_id}", response_model=SetupOutput, summary="Update an existing setup configuration.",
    description="Updates an existing setup configuration identified by `setup_id` with provided details. Supports updating playlists, devices, and setup name. After update, it sends an `update_setup` instruction to all associated devices via Redis pub/sub. Devices listening on `/device/me/instructions` will receive this instruction and subsequently fetch updated setup information from `/device/me`.",
    tags=["Setups"],
    responses={
        200: {
            "description": "Setup updated successfully.",
            "content": {"application/json": {"example": {"id": 1, "name": "Updated Setup"}}},
        },
    })
async def update_setup(
    setup_id: int, data: SetupUpdate, session: SessionDep, redis: RedisDep, admin: AdminKeyDep
):
    try:
        # setup
        setup = session.exec(select(Setup).filter_by(id=setup_id)).first()
        if not setup:
            raise HTTPException(
                detail=f"Setup {setup_id} not dound",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if data.name:
            setup.name = data.name

        # remove playlists
        for playlist_id in data.playlists_to_delete:
            playlist = session.exec(
                select(Playlist).filter_by(id=playlist_id, setup_id=setup.id)
            ).first()
            if playlist:
                session.delete(playlist)

        # TODO: re-do - this check must be applied at the end on setup.playlist if so raise
        days = [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ]
        for day in days:
            # TODO: Ai generated make your own
            # Filter playlists that run on this specific day
            day_playlists = [p for p in data.playlists if getattr(p, day)]

            # Sort by start_time
            day_playlists.sort(key=lambda p: datetime.strptime(p.start_time, "%H:%M"))

            # Compare each playlist with the next one
            for i in range(len(day_playlists) - 1):
                current_end = datetime.strptime(day_playlists[i].end_time, "%H:%M")
                next_start = datetime.strptime(day_playlists[i + 1].start_time, "%H:%M")
                if current_end > next_start:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Playlists '{day_playlists[i].name}' and '{day_playlists[i + 1].name}' overlap on {day}",
                    )

        # new playlist
        for playlist_data in data.playlists_to_add:
            if len(playlist_data.images) == 0 and len(playlist_data.videos) == 0:
                raise HTTPException(detail=f"Playlist {playlist_data.name} must have at least one image or video", status_code=status.HTTP_400_BAD_REQUEST)


            start_time = datetime.strptime(playlist_data.start_time, "%H:%M")
            end_time = datetime.strptime(playlist_data.end_time, "%H:%M")

            if start_time >= end_time:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Playlist {playlist_data.name} start_time must be before end_time",
                )

            new_playlist = Playlist(
                name=playlist_data.name,
                start_time=playlist_data.start_time,
                end_time=playlist_data.end_time,
                monday=playlist_data.monday,
                tuesday=playlist_data.tuesday,
                wednesday=playlist_data.wednesday,
                thursday=playlist_data.thursday,
                friday=playlist_data.friday,
                saturday=playlist_data.saturday,
                sunday=playlist_data.sunday,
                setup_id=setup.id,
            )
            session.add(new_playlist)
            session.flush()

            for image in playlist_data.images:
                session.add(
                    Image(
                        url=image.url,
                        duration=image.duration,
                        playlist_id=new_playlist.id,
                    )
                )

            for video_url in playlist_data.videos:
                session.add(Video(url=video_url, playlist_id=new_playlist.id))

        # update playlists
        for playlist_update in data.playlists_to_update:
            playlist = session.exec(
                select(Playlist).filter_by(id=playlist_update.id, setup_id=setup.id)
            ).first()
            if playlist:

                # remove images
                for image_id in playlist_update.images_to_delete:
                    image = session.exec(
                        select(Image).filter_by(id=image_id, playlist_id=playlist.id)
                    ).first()
                    if image:
                        session.delete(image)
                # add images
                for image in playlist_update.images_to_add:
                    session.add(
                        Image(
                            url=image.url,
                            duration=image.duration,
                            playlist_id=playlist.id,
                        )
                    )

                # remove videos
                for video_id in playlist_update.videos_to_delete:
                    video = session.exec(
                        select(Video).filter_by(id=video_id, playlist_id=playlist.id)
                    ).first()
                    if video:
                        session.delete(video)

                # add videos
                for video_url in playlist_update.videos_to_add:
                    session.add(Video(url=video_url, playlist_id=playlist.id))

        # add devices
        for device_id in data.devices_to_add:
            device = session.exec(select(Device).filter_by(id=device_id)).first()
            if device:
                device.setup_id = setup.id
                session.add(device)

        # remove devices
        for device_id in data.devices_to_remove:
            device = session.exec(
                select(Device).filter_by(id=device_id, setup_id=setup.id)
            ).first()
            if device:
                device.setup_id = None
                session.add(device)
        # TODO: check for unqiue names across setup.playlists.name before notifying users for an update + raise
        # notify linked devices with instruction of update setp
        session.commit()
        for device in setup.devices:
            instruction = json.dumps({"instruction": "update_setup"})
            await redis.publish(f"device:{device.id}:instructions", instruction)

        setup_structure = SetupOutput(
            name=setup.name,
            id=setup.id,
            devices=[
                DevicePublicOutput.to_setup_model(device)
                for device in setup.devices
            ],
            data=setup.data,
        )
        return setup_structure
    except HTTPException as e:
        session.rollback()
        raise
    except Exception as e:
        session.rollback()
        raise


@router.get("/generate-upload-url/{file_name}", summary="Generate a pre-signed URL for file uploads to S3.",
    description="Generates a pre-signed URL that allows uploading files directly to an S3 bucket. Returns the upload URL and the file's public URL.",
    tags=["S3"])
async def generate_upload_url(
    file_name: str, session: SessionDep, admin: AdminKeyDep
) -> S3PreSignedUrlOutput:
    """Generate pre-signed URL to upload files"""
    try:

        s3_client = get_s3_client()

        # prefix key with uudi4 for unqiue key
        key = f"{uuid.uuid4()}_{file_name}"
        bucket_name = os.getenv("AWS_S3_BUCKET_NAME")
        expiration = 3600
        pre_signed_url = s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params={"Bucket": bucket_name, "Key": key},
            ExpiresIn=expiration,
        )

        region = os.getenv("AWS_REGION")
        # TODO: maybe yandex serv uses deffrent url pattern
        file_url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{key}"
        return {"upload_url": pre_signed_url, "file_url": file_url}

    except NoCredentialsError:
        raise HTTPException(
            detail="AWS credentials not found", status_code=status.HTTP_403_FORBIDDEN
        )
    except Exception as e:
        raise HTTPException(
            detail=str(e), status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
