import asyncio, sys
from google.genai import types
from google.adk import Runner
from google.adk.sessions import InMemorySessionService
from lab_spike.agent import root_agent, llm_workflow

async def run(wf, payload):
    svc = InMemorySessionService()
    runner = Runner(node=wf, app_name="spike", session_service=svc, auto_create_session=True)
    msg = types.Content(role="user", parts=[types.Part(text=payload)])
    outs = []
    async for ev in runner.run_async(user_id="u", session_id="s", new_message=msg):
        if ev.output is not None:
            outs.append((ev.author, ev.output))
    return outs

if __name__ == "__main__":
    import json
    wf = llm_workflow if "--llm" in sys.argv else root_agent
    for p in [{"test": "Hemoglobin", "value": 11.0, "low": 12.0, "high": 15.5},
              {"test": "Hemoglobin", "value": 6.2, "low": 12.0, "high": 15.5}]:
        print(json.dumps(p))
        for who, out in asyncio.run(run(wf, json.dumps(p))):
            print("  ", who, "->", out)
