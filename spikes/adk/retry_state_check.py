import asyncio
from google.genai import types
from google.adk import Runner, Workflow, Context
from google.adk.workflow import RetryConfig, node
from google.adk.sessions import InMemorySessionService
calls={"n":0}
@node(retry_config=RetryConfig(max_attempts=3, initial_delay=0.01, jitter=0.0))
def flaky(node_input: str, ctx: Context) -> str:
    calls["n"]+=1
    if calls["n"]<3: raise ValueError("boom")
    ctx.state["seen"]="yes"
    return "ok"
def reader(node_input: str, ctx: Context) -> str:
    return f"state={ctx.state.get('seen')}"
wf=Workflow(name="t", edges=[("START", flaky, reader)])
async def main():
    r=Runner(node=wf, app_name="t", session_service=InMemorySessionService(), auto_create_session=True)
    async for ev in r.run_async(user_id="u",session_id="s",new_message=types.Content(role="user",parts=[types.Part(text="x")])):
        if ev.output is not None: print(ev.output)
    print("calls",calls)
if __name__ == "__main__":
    asyncio.run(main())
