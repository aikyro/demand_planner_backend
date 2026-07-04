"""HTTP client to the ADK service (separate repo). Guarded by X-ADK-Secret."""
import httpx
from typing import List, Optional
from app.core.config import settings


async def create_session(
    input_paths: List[str],
    company_id: str,
    title: str = "New Session",
    user_id: str = "system"
) -> dict:
    """Create a new agent session."""
    payload = {
        "input_paths": input_paths,
        "company_id": company_id,  # Keep for ADK server reference
        "title": title,
        "user_id": user_id,
        "state": {
            "company_id": company_id,  # ← Store in session state for tools
        }
    }
    headers = {"X-ADK-Secret": settings.ADK_SECRET}
    timeout = httpx.Timeout(30.0, read=60.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{settings.ADK_URL}/sessions", json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def list_sessions() -> List[dict]:
    """List all sessions."""
    headers = {"X-ADK-Secret": settings.ADK_SECRET}
    timeout = httpx.Timeout(10.0, read=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{settings.ADK_URL}/sessions", headers=headers)
        resp.raise_for_status()
        return resp.json()


async def get_session(session_id: str) -> dict:
    """Get session details."""
    headers = {"X-ADK-Secret": settings.ADK_SECRET}
    timeout = httpx.Timeout(10.0, read=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{settings.ADK_URL}/sessions/{session_id}", headers=headers)
        resp.raise_for_status()
        return resp.json()


async def get_session_history(session_id: str) -> dict:
    """Get chat history for a session."""
    headers = {"X-ADK-Secret": settings.ADK_SECRET}
    timeout = httpx.Timeout(10.0, read=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{settings.ADK_URL}/sessions/{session_id}/history", headers=headers)
        resp.raise_for_status()
        return resp.json()


async def delete_session(session_id: str) -> dict:
    """Delete a session."""
    headers = {"X-ADK-Secret": settings.ADK_SECRET}
    timeout = httpx.Timeout(10.0, read=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.delete(f"{settings.ADK_URL}/sessions/{session_id}", headers=headers)
        resp.raise_for_status()
        return resp.json()


async def stream_chat(session_id: str, message: str, user_id: str = "system", company_id: str = None) -> dict:
    """Send a chat message and get streaming response."""
    payload = {
        "session_id": session_id,
        "message": message,
        "user_id": user_id,
        "state": {
            "company_id": company_id,
            "session_id": session_id  # ← Also pass session_id in state for tools
        }
    }
    headers = {"X-ADK-Secret": settings.ADK_SECRET}
    timeout = httpx.Timeout(60.0, read=1800.0)  # Long timeout for streaming
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{settings.ADK_URL}/run/stream", json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


# Keep backward compatibility
async def run_forecast(session_id: str, company_id: str, aggregation: str,
                       horizon: int, mapping: dict, dataset_name: str) -> dict:
    """Legacy function - use create_session + stream_chat instead."""
    payload = {
        "session_id": session_id,
        "company_id": company_id,
        "aggregation": aggregation,
        "horizon": horizon,
        "mapping": mapping,
        "dataset_name": dataset_name,
    }
    headers = {"X-ADK-Secret": settings.ADK_SECRET}
    timeout = httpx.Timeout(60.0, read=1800.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{settings.ADK_URL}/run", json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()
