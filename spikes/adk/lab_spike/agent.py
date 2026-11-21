"""ADK 2.0 spike: function nodes, router, parallel fan-out/fan-in, retry, optional Gemini node.

Run without any key:   python run_spike.py
Run with Gemini node:  GOOGLE_API_KEY=... python run_spike.py --llm
Browse in adk web:     adk web .   (then pick lab_spike)
"""
import os
from pydantic import BaseModel

from google.adk import Agent, Event, Workflow
from google.adk.workflow import JoinNode, RetryConfig


class Row(BaseModel):
    test: str
    value: float
    low: float
    high: float


class Flagged(BaseModel):
    test: str
    value: float
    flag: str  # low | normal | high
    critical: bool


# --- deterministic function nodes -------------------------------------------------
def parse_input(node_input: dict) -> Row:
    """Stand-in for extract: payload dict -> typed Row."""
    return Row(**node_input)


def flag_engine(node_input: Row) -> Flagged:
    flag = "low" if node_input.value < node_input.low else "high" if node_input.value > node_input.high else "normal"
    critical = node_input.test == "Hemoglobin" and node_input.value < 7.0
    return Flagged(test=node_input.test, value=node_input.value, flag=flag, critical=critical)


def critical_router(node_input: Flagged):
    # Router: returns an Event carrying a route; output passes through unchanged.
    return Event(output=node_input, route="CRITICAL" if node_input.critical else "OK")


def urgent_template(node_input: Flagged) -> dict:
    return {"urgent": True, "en": f"{node_input.test} is critically abnormal. Please see a doctor today.",
            "hi": f"{node_input.test} का मान गंभीर रूप से असामान्य है। कृपया आज ही डॉक्टर से मिलें।"}


def render_en(node_input: Flagged) -> dict:
    return {"en": f"Your {node_input.test} is {node_input.flag} compared with the printed range."}


def render_hi(node_input: Flagged) -> dict:
    word = {"low": "कम", "high": "अधिक", "normal": "सामान्य"}[node_input.flag]
    return {"hi": f"आपका {node_input.test} रिपोर्ट में छपे दायरे के मुकाबले {word} है।"}


def safety_check(node_input: dict) -> dict:
    # JoinNode output: {"render_en": {...}, "render_hi": {...}}
    merged = {"urgent": False}
    for part in node_input.values():
        merged.update(part)
    return merged


# --- optional LLM node with typed output ------------------------------------------
class Plain(BaseModel):
    sentence: str


llm_node = Agent(
    name="plan_statement",
    model=os.environ.get("SPIKE_MODEL", "gemini-3.1-flash-lite"),
    instruction="Write one plain sentence stating whether the value is low, normal or high. "
                "Do not diagnose. Input is JSON with test, value, flag.",
    output_schema=Plain,
    retry_config=RetryConfig(max_attempts=3),
)

join = JoinNode(name="join")

root_agent = Workflow(
    name="lab_spike",
    edges=[
        ("START", parse_input, flag_engine, critical_router),
        (critical_router, {"CRITICAL": urgent_template, "OK": (render_en, render_hi)}),
        ((render_en, render_hi), join, safety_check),
    ],
)

llm_workflow = Workflow(
    name="lab_spike_llm",
    edges=[("START", parse_input, flag_engine, llm_node)],
)
