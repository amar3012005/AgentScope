from agentscope_blaiq.tui import _comma_list, _extract_event_payload, _strip_data_prefix


def test_strip_data_prefix_handles_double_wrapped_sse() -> None:
    assert _strip_data_prefix("data: data: {\"ok\": true}") == "{\"ok\": true}"


def test_extract_event_payload_parses_double_prefixed_json() -> None:
    payload = _extract_event_payload('data: data: {"type":"workflow_complete","data":{"ok":true}}')
    assert payload is not None
    assert payload["type"] == "workflow_complete"
    assert payload["data"]["ok"] is True


def test_extract_event_payload_ignores_invalid_lines() -> None:
    assert _extract_event_payload("event: ping") is None
    assert _extract_event_payload("data: [DONE]") is None


def test_comma_list_uses_defaults_when_blank(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert _comma_list("Allowed tools", ["a", "b"]) == ["a", "b"]


def test_comma_list_parses_csv_input(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "alpha, beta , gamma")
    assert _comma_list("Allowed tools", ["a"]) == ["alpha", "beta", "gamma"]
