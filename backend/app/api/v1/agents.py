"""
Agent API endpoints - proxies requests to ADK service.
"""
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.core.deps import get_current_user, CurrentUser
from app.services.metrics_service import MetricsService, AgentService
from app.core.redis import redis_client
import app.adk_client as adk_client

router = APIRouter(tags=["agents"])

class CreateSessionIn(BaseModel):
    input_paths: list[str]
    title: str = "New Session"


class ChatIn(BaseModel):
    session_id: str | None = None
    message: str


@router.get("/metrics")
async def metrics(session_id: str = Query(...),
                  user: CurrentUser = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)):
    return await MetricsService(db, user.company_id).session_metrics(session_id)


@router.get("/traces")
async def traces(session_id: str = Query(...),
                 user: CurrentUser = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    rows = await AgentService(db, user.company_id).traces(session_id)
    return [
        {"agent_type": t.agent_type, "step": t.step, "status": t.status,
         "output_summary": t.output_summary,
         "created_at": t.created_at.isoformat() if t.created_at else None}
        for t in rows
    ]


# ===========================================
# ADK Session Management (proxy to ADK service)
# ===========================================

@router.post("/sessions")
async def create_agent_session(
    data: CreateSessionIn,
    user: CurrentUser = Depends(get_current_user),
):
    """Create a new agent chat session."""
    # Create session in ADK
    result = await adk_client.create_session(
        input_paths=data.input_paths,
        company_id=user.company_id,
        title=data.title,
        user_id=user.id,
    )

    return result


@router.get("/sessions")
async def list_agent_sessions(
    user: CurrentUser = Depends(get_current_user),
):
    """List all agent sessions."""
    return await adk_client.list_sessions()


@router.get("/sessions/{session_id}")
async def get_agent_session(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """Get agent session details."""
    return await adk_client.get_session(session_id)


# ===========================================


@router.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """Get chat history for a session."""
    return await adk_client.get_session_history(session_id)


@router.get("/sessions/{session_id}/progress")
async def stream_session_progress(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """Stream progress updates for 2 background tasks involving db insertion for a session via SSE."""
    import redis.asyncio as aioredis
    from app.core.config import settings

    async def event_generator():
        # Create Redis client for subscription
        redis_url = settings.REDIS_URL
        pubsub = None

        try:
            # Connect to Redis
            redis = aioredis.from_url(redis_url, decode_responses=True)

            # Subscribe to progress channel
            channel = f"progress:{session_id}"
            pubsub = redis.pubsub()
            await pubsub.subscribe(channel)

            # Also get initial progress from hash (if any)
            progress_key = f"progress:{session_id}"
            initial_data = await redis.hgetall(progress_key)
            if initial_data and 'modeling_data' in initial_data:
                # Send initial state
                yield f"data: {initial_data['modeling_data']}\n\n"

            # Stream messages
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    yield f"data: {message['data']}\n\n"
        except Exception as e:
            print(f"[ERROR] Progress stream: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            if pubsub:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            await redis.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@router.delete("/sessions/{session_id}")
async def delete_agent_session(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """Delete an agent session."""
    return await adk_client.delete_session(session_id)


@router.post("/run/stream")
async def stream_agent_chat(
    data: ChatIn,
    user: CurrentUser = Depends(get_current_user),
):
    """Send chat message and stream response (SSE)."""
    import httpx

    payload = {
        "session_id": data.session_id,
        "message": data.message,
        "user_id": user.id,
    }
    headers = {
        "X-ADK-Secret": "change-me-adk-secret",  # TODO: use settings.ADK_SECRET
    }

    async def event_generator():
        async with httpx.AsyncClient(timeout=1800.0) as client:
            async with client.stream(
                "POST",
                f"http://localhost:9000/run/stream",
                json=payload,
                headers=headers,
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        yield line + "\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


# Keep old endpoints for backward compatibility
@router.post("/agents/chat")
async def chat(data: ChatIn, user: CurrentUser = Depends(get_current_user),
               db: AsyncSession = Depends(get_db)):
    return await AgentService(db, user.company_id).chat(data.session_id, data.message)


@router.post("/agents/diagnose")
async def diagnose(session_id: str = Query(...),
                   user: CurrentUser = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    return await AgentService(db, user.company_id).diagnose(session_id)
