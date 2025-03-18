import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlmodel import select

from ..dependencies import DeviceKeyDep, RedisDep, SessionDep, AdminKeyDep
from ..models.device import (
    DeleteDeviceResponse,
    Device,
    DeviceInput,
    DeviceOutput,
    DevicePublicOutput,
    DeviceUpdate,
    SnapshotInstructionInput,
)
from ..models.setup import Setup
from ..utils import generate_api_key

router = APIRouter()



@router.post("/", response_model=DevicePublicOutput, summary="Activate a device via pin.",
    description="Activates an awaiting client via pin. Checks if a subscriber exists on the channel corresponding to the provided pin, validates the device name, generates a unique API key, adds the device to the database, and sends the device name and API key to the client via Redis pub/sub.",
    tags=["Devices"],
    responses={
        200: {
            "description": "Device activated successfully.",
            "content": {"application/json": {"example": {"id": 1, "name": "Device 1"}}},
        },
        404: {
            "description": "No client awaiting with the provided pin.",
            "content": {"application/json": {"example": {"detail": "No Client awaiting with the following pin: 123456"}}},
        },
        409: {
            "description": "Device name already exists.",
            "content": {"application/json": {"example": {"detail": "Device name Device 1 already exsist."}}},
        },
    })
async def create_device(
    data: DeviceInput, redis: RedisDep, session: SessionDep, admin: AdminKeyDep
) -> DevicePublicOutput:
    """Activates an awaiting client via pin"""
    # Check if no subscriber on channel data.code
    result = await redis.pubsub_numsub(data.code)
    channel_subscriber_number = result[0][1]
    if channel_subscriber_number == 0:
        raise HTTPException(
            detail=f"No Client awaiting with the following pin: {data.code}",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    # Unique name
    device_name_exists = session.exec(select(Device).filter_by(name=data.name)).first()
    if device_name_exists:
        raise HTTPException(
            detail=f"Device name {data.name} already exsist.",
            status_code=status.HTTP_409_CONFLICT,
        )
    # Generate unique api key
    while True:
        api_key = generate_api_key()
        api_key_exists = session.exec(select(Device).filter_by(api_key=api_key)).first()
        if not api_key_exists:
            break
    # Add device in DB
    new_device = Device(
        name=data.name,
        location=data.location,
        last_seen=datetime.now(timezone.utc),
        api_key=api_key,
    )
    session.add(new_device)
    session.commit()
    # Send data to channel data.code
    await redis.publish(
        data.code, json.dumps({"name": new_device.name, "api_key": new_device.api_key})
    )
    # Return new device data to admin
    return new_device


@router.get("/me", summary="Get device information by API key.",
    description="Retrieves the device information using the API key provided in the request headers. Returns the device details and linked setup information.",
    tags=["Devices"],
    response_model=DeviceOutput,
    responses={
        200: {
            "description": "Device information retrieved successfully.",
            "content": {"application/json": {"example": {"id": 1, "name": "Device 1", "setup": "setup_details"}}},
        },
    })
async def get_device_info_by_api_key(device: DeviceKeyDep) -> DeviceOutput:
    return device


# get all devices info
@router.get("/", response_model=list[DevicePublicOutput], summary="Get all devices information.",
    description="Retrieves a list of all devices stored in the database.",
    tags=["Devices"],
    responses={
        200: {
            "description": "List of devices retrieved successfully.",
            "content": {"application/json": {"example": [{"id": 1, "name": "Device 1", "location": "New York", "lastseen": "2025...", "setup_id": 1}, {"id": 2, "name": "Device 2", "location": "New York", "lastseen": "2025...", "setup_id": "null"}]}},
        },
    })
async def get_all_devices_info(session: SessionDep, admin: AdminKeyDep) -> list[DevicePublicOutput]:
    devices = session.exec(select(Device)).all()

    return devices


# we need a route to delete a device
@router.delete(
    "/{device_id}",
    response_model=DeleteDeviceResponse,
    summary="Delete a device.",
    description="Deletes a device identified by `device_id` from the database.",
    tags=["Devices"],
    responses={
        200: {
            "description": "Device deleted successfully.",
            "content": {"application/json": {"example": {"detail": "Device 1 deleted successfully."}}},
        },
        404: {
            "description": "Device not found.",
            "content": {"application/json": {"example": {"detail": "Device 1 not found."}}},
        },
    }
)
async def delete_device(device_id: int, session: SessionDep, admin: AdminKeyDep) -> DeleteDeviceResponse:
    device = session.exec(select(Device).filter_by(id=device_id)).first()
    if not device:
        raise HTTPException(
            detail=f"Device {device_id} not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    session.delete(device)
    session.commit()
    return {"detail": f"Device {device_id} deleted successfully."}


@router.put(
    "/{device_id}",
    response_model=DevicePublicOutput,
    summary="Update device information.",
    description="Updates the information of a device identified by `device_id`. Supports updating the device name and setup association. Checks for unique device names and valid setup IDs.",
    tags=["Devices"],
    responses={
        200: {
            "description": "Device information updated successfully.",
            "content": {"application/json": {"example": {"id": 1, "name": "Updated Device 1"}}},
        },
        404: {
            "description": "Device or Setup not found.",
            "content": {"application/json": {"example": {"detail": "Device 1 not found."}}},
        }
    }
)
async def update_device_info(
    device_id: int, data: DeviceUpdate, session: SessionDep, admin: AdminKeyDep
) -> DevicePublicOutput:
    device = session.exec(select(Device).filter_by(id=device_id)).first()
    if not device:
        raise HTTPException(
            detail=f"Device {device_id} not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    update_data = data.model_dump(exclude_unset=True)
    if "name" in update_data:
        device_name_exist = session.exec(
            select(Device).filter_by(name=update_data["name"])
        ).first()
        if device_name_exist:
            raise HTTPException(
                detail=f"Device name {update_data['name']} already in use.",
                status_code=status.HTTP_409_CONFLICT,
            )


    device.sqlmodel_update(update_data)
    session.add(device)
    session.commit()

    return device


@router.get("/me/instructions", summary="Stream device instructions.",
    description="Streams instructions to a subscribed device via Redis pub/sub. Updates the device's last seen timestamp and sends device status updates to the `devices:status` channel. Includes a heartbeat mechanism to maintain the connection.",
    tags=["Devices"],
    responses={
        200: {
            "description": "Streaming instructions.",
            "content": {"text/event-stream": {"example": "event: message\ndata: {\"instruction\": \"update_setup\"}\n\n"}},
        },
    })
async def get_current_device_instructions(
    device: DeviceKeyDep, redis: RedisDep, session: SessionDep
):
    """Stream instructions to subscribed device"""

    device.last_seen = datetime.now(timezone.utc)
    session.add(device)
    session.commit()

    status_message = json.dumps({"id": device.id, "status": "online"})
    await redis.publish("devices:status", status_message)
    await redis.sadd("online_devices", device.id)

    async def event_generator():
        """Generator for streaming data"""
        pubsub = redis.pubsub()
        await pubsub.subscribe(f"device:{device.id}:instructions")
        queue = asyncio.Queue()

        async def message_listener():
            nonlocal redis
            try:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        await queue.put(f"event: message\ndata: {message['data']}\n\n")
            except asyncio.CancelledError:
                await redis.srem("online_devices", device.id)
                status_message = json.dumps({"id": device.id, "status": "offline"})
                await redis.publish("devices:status", status_message)
                await pubsub.unsubscribe()

        async def heartbeat_sender():
            """Task to send a heartbeat"""
            try:
                while True:
                    await asyncio.sleep(10)
                    await queue.put("event: heartbeat\ndata: heartbeat\n\n")
            except asyncio.CancelledError:
                pass

        try:
            listener_task = asyncio.create_task(message_listener())
            heartbeat_task = asyncio.create_task(heartbeat_sender())

            while True:
                item = await queue.get()

                yield item
        finally:
            heartbeat_task.cancel()
            listener_task.cancel()

            device.last_seen = datetime.now(timezone.utc)
            session.add(device)
            session.commit()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# route for admin to see list of online and offline users in real-time
@router.get("/status", summary="Get all devices status.",
    description="Streams the status of all devices (online/offline) in real-time. Subscribes to the `devices:status` channel via Redis pub/sub. Includes a heartbeat mechanism to maintain the connection.",
    tags=["Devices"],
    responses={
        200: {
            "description": "Streaming device status.",
            "content": {"text/event-stream": {"example": "event: update\ndata: {\"id\": 1, \"status\": \"online\"}\n\n"}},
        },
    })
async def get_all_devices_status(redis: RedisDep, admin: AdminKeyDep):
    async def event_generator():
        pubsub = redis.pubsub()
        await pubsub.subscribe("devices:status")
        queue = asyncio.Queue()

        async def message_listener():
            try:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        await queue.put(f"event: update\ndata: {message['data']}\n\n")
            except asyncio.CancelledError:
                await pubsub.unsubscribe()

        async def heartbeat_sender():
            """Task to send a heartbeat"""
            try:
                while True:
                    await asyncio.sleep(10)
                    await queue.put("event: heartbeat\ndata: heartbeat\n\n")
            except asyncio.CancelledError:
                pass

        try:
            listener_task = asyncio.create_task(message_listener())
            heartbeat_task = asyncio.create_task(heartbeat_sender())

            init_devices = await redis.smembers("online_devices")
            init_response = f"event: message\ndata: {list(init_devices)}\n\n"
            yield init_response

            while True:
                item = await queue.get()
                yield item
        finally:
            listener_task.cancel()
            heartbeat_task.cancel()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{device_id}", response_model=DevicePublicOutput, summary="Get device information.",
    description="Retrieves the information of a device identified by `device_id`.",
    tags=["Devices"],
    responses={
        200: {
            "description": "Device information retrieved successfully.",
            "content": {"application/json": {"example": {"id": 1, "name": "Device 1", "lastseen": "2025...", "setup_id": 1}}},
        },
        404: {
            "description": "Device not found.",
            "content": {"application/json": {"example": {"detail": "Device with id 1 not found"}}},
        },
    })
async def get_device_info(device_id: int, session: SessionDep, admin: AdminKeyDep) -> DevicePublicOutput:
    device = session.exec(select(Device).filter_by(id=device_id)).first()
    if not device:
        raise HTTPException(
            detail=f"Device with id {device_id} not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return device

@router.put("/{device_id}/instructions/take-snapshot", summary="Send snapshot instruction to a device.",
    description="Sends a snapshot instruction to a specific device via Redis pub/sub. The instruction includes a URL where the device can upload the screenshot. Checks if the device exists and is currently online before sending the instruction. The device, upon receiving the 'snapshot' instruction, will capture a screenshot and upload it to the provided URL.",
    tags=["Devices"],
    responses={
        200: {
            "description": "Snapshot instruction sent successfully.",
            "content": {"application/json": {"example": {"detail": "Instruction sent successfully"}}},
        },
        404: {
            "description": "Device not found.",
            "content": {"application/json": {"example": {"detail": "Device 1 not found"}}},
        },
        409: {
            "description": "Device is offline.",
            "content": {"application/json": {"example": {"detail": "Device 1 is offline"}}},
        },
    })
async def send_snapshot_instruction(
    data: SnapshotInstructionInput, device_id: int, redis: RedisDep, session: SessionDep, admin: AdminKeyDep
):
    device = session.exec(select(Device).filter_by(id=device_id)).first()
    if not device:
        raise HTTPException(
            detail=f"Device {device_id} not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if (await redis.pubsub_numsub(f"device:{device.id}:instructions"))[0][1] == 0:
        raise HTTPException(
            detail=f"Device {device_id} is offline",
            status_code=status.HTTP_409_CONFLICT,
        )

    # now we just send the actual instruction to that one
    instruction = json.dumps({"instruction": "snapshot", "url": data.url})
    await redis.publish(f"device:{device.id}:instructions", instruction)

    return {"detail": "Instruction sent successfully"}
