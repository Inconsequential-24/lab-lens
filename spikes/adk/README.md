# ADK 2.0 spike

Confirms the ADK 2.0 API before the real pipeline is built on it. Verified with `google-adk==2.15.0` (see `requirements.txt`).

Run: `pip install -r requirements.txt && python run_spike.py` (no key needed) or `adk web .` and pick `lab_spike`.
Tests: `pytest` (offline). `python retry_state_check.py` shows retry and shared state. The Gemini node (`python run_spike.py --llm`) needs `GOOGLE_API_KEY` and has NOT been run yet.

## Confirmed
| Item | Result |
|---|---|
| Function node | Plain function `f(node_input: T) -> U`; Pydantic types pass between nodes |
| Edges | `("START", a, b, c)` chain; `(router, {"ROUTE": node})` |
| Router | Function returns `Event(output=..., route="X")` |
| Parallel fan-out | Route value can be a tuple of nodes: `{"OK": (render_en, render_hi)}` |
| Fan-in | `JoinNode`; output is a dict keyed by predecessor node name |
| Retry | `@node(retry_config=RetryConfig(max_attempts=3, ...))`; failed node retried, then continued |
| Shared state | `ctx: Context` param; `ctx.state["k"] = v` readable in later nodes |
| Running from code | `Runner(node=workflow, app_name=..., session_service=InMemorySessionService(), auto_create_session=True).run_async(...)` |
| Agent retry/typed output | `Agent(..., output_schema=Model, retry_config=RetryConfig(...))` constructs; behaviour with live Gemini not yet tested |

## Not yet confirmed
- Live Gemini call with `output_schema` (needs a key); token usage fields for the cost tracker.
- `adk web` UI rendering of the graph (not opened in this sandbox).
- Retry count is not persisted across resume (ADK log message), fine for our short runs.
