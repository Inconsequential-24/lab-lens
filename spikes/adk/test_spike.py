"""Offline tests for the ADK spike (no API key needed)."""
import asyncio, json
from google.genai import types
from google.adk import Runner
from google.adk.sessions import InMemorySessionService
from lab_spike.agent import root_agent


def run(payload):
    async def go():
        r = Runner(node=root_agent, app_name="t", session_service=InMemorySessionService(), auto_create_session=True)
        msg = types.Content(role="user", parts=[types.Part(text=json.dumps(payload))])
        return [e.output async for e in r.run_async(user_id="u", session_id="s", new_message=msg) if e.output is not None]
    return asyncio.run(go())


def test_normal_goes_through_fanout_and_join():
    last = run({"test": "Hemoglobin", "value": 11.0, "low": 12.0, "high": 15.5})[-1]
    assert last["urgent"] is False and "en" in last and "hi" in last


def test_critical_takes_urgent_route_only():
    last = run({"test": "Hemoglobin", "value": 6.2, "low": 12.0, "high": 15.5})[-1]
    assert last["urgent"] is True and "en" in last and "hi" in last
