import asyncio
import random

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from ..dependencies import RedisDep
from ..models.device import DeviceCodeOutput

router = APIRouter()


@router.get(
    "/",
    response_model=DeviceCodeOutput,
    summary="Generate Unique Activation Code",
    description="This endpoint generates a unique 9-digit activation code using Redis INCR and a random seed. The counter is reset once the code reaches 999_999_999.",
    responses={
        200: {
            "description": "Unique activation code successfully generated.",
            "content": {"application/json": {"example": {"code": 123456789}}},
        },
    },
    tags=["Device Activation"],
)
async def get_unique_activation_code(redis: RedisDep) -> DeviceCodeOutput:
    """Generate a unique 9 numbers using using redis INCR and a random seed and reset if pin 999_999_999 reached"""
    if (await redis.exists("activation_code_counter")) == 0:
        seed_value = random.randint(100_000_000, 900_000_000)
        await redis.set("activation_code_counter", seed_value)
    unique_code = await redis.incr("activation_code_counter")

    if unique_code >= 999_999_999:
        await redis.set(
            "activation_code_counter", random.randint(100_000_000, 900_000_000)
        )
        unique_code = await redis.incr("activation_code_counter")

    return {"code": unique_code}


@router.get(
    "/{code}/status",
    summary="Stream Device Status by Activation Code",
    description="This endpoint streams the status updates of a device associated with the given activation code. It listens for changes and sends them via Server-Sent Events (SSE). If the code is unavailable, a 400 error will be returned.",
    responses={
        200: {
            "description": "Device status streaming started.",
            "content": {
                "text/event-stream": {
                    "example": "event: message\ndata: Device is active\n\n"
                }
            },
        },
        400: {
            "description": "Code is unavailable. Please request a new one.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Code is not available, please request another one."
                    }
                }
            },
        },
    },
    tags=["Device Activation"],
)
async def get_device_status_by_code(code: str, redis: RedisDep, request: Request):
    """Streams client status changes"""
    result = await redis.pubsub_numsub(code)
    channel_subscriber_number = result[0][1]
    if channel_subscriber_number != 0:
        raise HTTPException(
            detail=f"Code is not available pelas request another one",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    async def event_generator():
        """Generator for streaming data"""
        pubsub = redis.pubsub()
        await pubsub.subscribe(code)
        queue = asyncio.Queue()
        pubsub_cleaned_up = False

        async def message_listener():
            nonlocal pubsub_cleaned_up
            try:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        await queue.put(f"event: message\ndata: {message['data']}\n\n")
                        break
            except asyncio.CancelledError:
                await pubsub.unsubscribe()
                pubsub_cleaned_up = True

        async def timeout_trigger():
            """Time out after 10min of idle"""
            # TODO: time val as an env
            try:
                await asyncio.sleep(630)
                await queue.put("TIMEOUT")
            except asyncio.CancelledError:
                pass

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
            timeout_task = asyncio.create_task(timeout_trigger())

            while True:
                item = await queue.get()

                if item == "TIMEOUT":
                    break

                yield item

                if "heartbeat" not in item:
                    break
        finally:
            listener_task.cancel()
            heartbeat_task.cancel()
            timeout_task.cancel()

            if not pubsub_cleaned_up:
                await pubsub.unsubscribe(code)
                await pubsub.aclose()

    return StreamingResponse(event_generator(), media_type="text/event-stream")
