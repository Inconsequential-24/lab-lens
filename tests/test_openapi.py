"""openapi.yaml must match PLAN.md section 6 and the Pydantic models in schemas.py."""
from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

import pytest
import yaml

from lablens import schemas

ROOT = Path(__file__).resolve().parents[1]
SPEC = yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))
COMPONENTS = SPEC["components"]["schemas"]

PLAN_ENDPOINTS = {
    ("/v1/reports", "post"),
    ("/v1/reports/{report_id}", "get"),
    ("/v1/reports/{report_id}/save", "post"),
    ("/v1/history", "get"),
    ("/v1/history", "delete"),
    ("/v1/history/{report_id}", "delete"),
    ("/v1/history/trends", "get"),
    ("/v1/reports/{report_id}/chat", "post"),
    ("/healthz", "get"),
}
AUTH_REQUIRED = {
    ("/v1/reports/{report_id}/save", "post"),
    ("/v1/history", "get"),
    ("/v1/history", "delete"),
    ("/v1/history/{report_id}", "delete"),
    ("/v1/history/trends", "get"),
}
MODELS = [
    schemas.Value, schemas.RefRange, schemas.FlaggedTest, schemas.Citation,
    schemas.Statement, schemas.Explanation, schemas.Recommendation,
    schemas.RunMetrics, schemas.ReportResult, schemas.SavedReport,
]
ENUMS = [schemas.Flag, schemas.Severity, schemas.Panel]


def test_openapi_version():
    assert SPEC["openapi"].startswith("3.1")


@pytest.mark.parametrize("path,method", sorted(PLAN_ENDPOINTS))
def test_plan_endpoint_exists(path, method):
    assert method in SPEC["paths"].get(path, {}), f"{method.upper()} {path} missing"


def test_security_only_on_saved_history():
    for path, ops in SPEC["paths"].items():
        for method, op in ops.items():
            sec = op.get("security", SPEC.get("security", []))
            required = bool(sec) and {} not in sec
            assert required == ((path, method) in AUTH_REQUIRED), f"{method} {path}"
    assert SPEC["components"]["securitySchemes"]["googleIdToken"]["scheme"] == "bearer"


def test_chat_is_stretch():
    assert SPEC["paths"]["/v1/reports/{report_id}/chat"]["post"]["x-stretch"] is True


def test_report_type_and_language():
    props = COMPONENTS["UploadRequest"]["properties"]
    assert props["report_type"]["enum"] == ["synthetic", "real"]
    assert props["report_type"]["default"] == "synthetic"
    assert props["language"]["enum"] == ["en", "hi", "both"]


def test_rate_limit_429_everywhere_but_healthz():
    for path, ops in SPEC["paths"].items():
        for method, op in ops.items():
            if path != "/healthz":
                assert "429" in op["responses"], f"{method} {path}"
    headers = SPEC["components"]["responses"]["TooManyRequests"]["headers"]
    assert {"Retry-After", "X-RateLimit-Remaining"} <= set(headers)


def test_reason_codes():
    reasons = set(COMPONENTS["Error"]["properties"]["reason"]["enum"])
    for code in ("too_many_pages", "not_a_lab_report", "encrypted_pdf", "file_too_large",
                 "already_saved", "overlap", "consent_required", "rate_limited",
                 "daily_cap_reached", "no_tests_extracted", "provider_unavailable"):
        assert code in reasons
    for resp in SPEC["components"]["responses"].values():
        for media in resp.get("content", {}).values():
            if "example" in media:
                assert media["example"]["reason"] in reasons


@pytest.mark.parametrize("enum_cls", ENUMS, ids=lambda e: e.__name__)
def test_enum_matches(enum_cls: type[Enum]):
    assert COMPONENTS[enum_cls.__name__]["enum"] == [m.value for m in enum_cls]


def _enum_values(node) -> list | None:
    """Inline enum values in a JSON-schema fragment, ignoring $refs (checked separately)."""
    if not isinstance(node, dict):
        return None
    if "enum" in node:
        return list(node["enum"])
    if "const" in node:
        return [node["const"]]
    for key in ("anyOf", "oneOf", "allOf"):
        for sub in node.get(key, []):
            found = _enum_values(sub)
            if found is not None:
                return found
    return _enum_values(node.get("items"))


def _refs(node) -> set[str]:
    text = repr(node)
    return {m.rsplit("/", 1)[-1] for m in re.findall(r"#/(?:\$defs|components/schemas)/\w+", text)}


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_component_matches_model(model):
    comp = COMPONENTS[model.__name__]
    js = model.model_json_schema()
    assert set(comp["properties"]) == set(js["properties"]), "field names drifted"
    assert set(comp.get("required", [])) == set(js.get("required", [])), "required drifted"
    for name, prop in js["properties"].items():
        assert _enum_values(comp["properties"][name]) == _enum_values(prop), name
        assert _refs(comp["properties"][name]) == _refs(prop), name


def test_no_secrets_or_personal_data():
    text = (ROOT / "openapi.yaml").read_text(encoding="utf-8")
    patterns = [
        r"AIza[0-9A-Za-z_\-]{20,}",          # Google API key
        r"eyJ[0-9A-Za-z_\-]{10,}\.",         # JWT
        r"sk-[0-9A-Za-z]{16,}",
        r"[\w.+-]+@(?!anthropic)[\w-]+\.[a-z]{2,}",  # email
        r"(?<!\d)[6-9]\d{9}(?!\d)",          # Indian mobile number
        r"\b\d{4}\s?\d{4}\s?\d{4}\b",        # Aadhaar-like
        r"(?i)\b(mr|mrs|ms|dr)\.?\s+[A-Z][a-z]+",  # named person
    ]
    for pat in patterns:
        assert not re.search(pat, text), pat
