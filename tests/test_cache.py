from lablens.cache import REPORT_NODE, ResponseCache, build_prompt, file_sha256, pipeline_version


def test_roundtrip_report_and_node(tmp_path):
    c = ResponseCache(tmp_path / "c.sqlite")
    sha = file_sha256(b"pdf")
    v = pipeline_version({"prompt": "h1", "model": "m"})
    assert c.get(sha, REPORT_NODE, v, real_upload=False) is None
    c.put(sha, REPORT_NODE, v, {"flags": [1]}, real_upload=False)
    c.put(sha, "extract", v, {"rows": []}, real_upload=False)
    assert c.get(sha, REPORT_NODE, v, real_upload=False) == {"flags": [1]}
    assert c.get(sha, "extract", v, real_upload=False) == {"rows": []}
    assert ResponseCache(tmp_path / "c.sqlite").get(sha, "extract", v, real_upload=False) == {"rows": []}


def test_version_change_misses_and_chains_downstream():
    base = {"prompt": "p", "model": "m", "glossary": "1", "thresholds": {"a": 1}}
    ext = pipeline_version(base)
    assert ext == pipeline_version(dict(reversed(list(base.items()))))
    assert pipeline_version({**base, "model": "m2"}) != ext
    assert pipeline_version({"prompt": "r"}, upstream=ext) != pipeline_version({"prompt": "r"}, upstream="other")


def test_real_upload_bypasses_cache(tmp_path):
    c = ResponseCache(tmp_path / "c.sqlite")
    assert c.put("s", REPORT_NODE, "v", {"x": 1}, real_upload=True) is False
    assert c.get("s", REPORT_NODE, "v", real_upload=False) is None
    c.put("s", REPORT_NODE, "v", {"x": 1}, real_upload=False)
    assert c.get("s", REPORT_NODE, "v", real_upload=True) is None


def test_ttl_expiry(tmp_path, monkeypatch):
    c = ResponseCache(tmp_path / "c.sqlite", ttl_seconds=10)
    c.put("s", "n", "v", 1, real_upload=False)
    import lablens.cache as mod
    now = mod.time.time()
    monkeypatch.setattr(mod.time, "time", lambda: now + 11)
    assert c.get("s", "n", "v", real_upload=False) is None


def test_prompt_layout_static_prefix_first():
    p = build_prompt({"glossary": "G", "system_rules": "S"}, "REPORT")
    assert p == "S\n\nG\n\nREPORT"


def test_real_upload_is_required_keyword(tmp_path):
    import pytest
    c = ResponseCache(tmp_path / "c.sqlite")
    with pytest.raises(TypeError):
        c.get("s", "n", "v")
    with pytest.raises(TypeError):
        c.put("s", "n", "v", 1)
