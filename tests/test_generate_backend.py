import io
import json
import subprocess
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from yt_ruby_subs import generate
from yt_ruby_subs.errors import CliError


def test_read_existing_vtt_normalizes_text_and_rejects_invalid(tmp_path: Path) -> None:
    valid = tmp_path / "valid.vtt"
    valid.write_bytes("\ufeffWEBVTT\r\n\r\n00:00.000 --> 00:01.000\r\nText\r\n".encode("utf-8"))
    invalid = tmp_path / "invalid.vtt"
    invalid.write_text("not vtt", encoding="utf-8")

    assert generate.read_existing_vtt(valid, "webvtt") == "WEBVTT\n\n00:00.000 --> 00:01.000\nText\n"
    with pytest.raises(CliError, match="existing webvtt does not start"):
        generate.read_existing_vtt(invalid, "webvtt")


def test_validate_vtt_reports_empty_bad_duration_and_disorder() -> None:
    text = """WEBVTT

00:00:02.000 --> 00:00:01.000
Backwards

00:00:00.500 --> 00:00:01.000
"""

    cues, warnings = generate.validate_vtt(text, "webvtt")

    assert len(cues) == 2
    assert "webvtt: 1 empty cue(s)" in warnings
    assert "webvtt: 1 cue(s) with non-positive or negative duration" in warnings
    assert "webvtt: 1 cue(s) out of chronological order" in warnings


def test_validate_outputs_reports_cue_count_and_text_mismatch() -> None:
    corrected = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n仕事\n"
    ruby_changed = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n別\n"
    ruby_extra = ruby_changed + "\n00:00:02.000 --> 00:00:03.000\n追加\n"

    assert generate.validate_outputs(corrected, ruby_changed) == [
        "1 ruby cue(s) differ in text from the corrected transcript"
    ]
    assert generate.validate_outputs(corrected, ruby_extra) == [
        "cue count differs (corrected=1, ruby=2); ruby output may have dropped or merged lines"
    ]


def test_parse_chat_api_payload_accepts_supported_shapes() -> None:
    assert generate.parse_chat_api_payload({"webvtt": "direct"}, ("webvtt",)) == {"webvtt": "direct"}
    assert generate.parse_chat_api_payload(
        {"choices": [{"message": {"parsed": {"summary": "parsed"}}}]},
        ("summary",),
    ) == {"summary": "parsed"}
    assert generate.parse_chat_api_payload(
        {"choices": [{"message": {"content": [{"type": "text", "text": '```json\n{"summary": "text"}\n```'}]}}]},
        ("summary",),
    ) == {"summary": "text"}


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"choices": []},
        {"choices": [{"message": "not an object"}]},
        {"choices": [{"message": {"content": ""}}]},
    ],
)
def test_parse_chat_api_payload_reports_invalid_shapes(payload: Any) -> None:
    with pytest.raises(CliError):
        generate.parse_chat_api_payload(payload, ("summary",))


def test_extract_json_object_reports_missing_object() -> None:
    with pytest.raises(CliError, match="does not contain a JSON object"):
        generate.extract_json_object("no json here")


def test_run_claude_returns_structured_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(generate, "resolve_command", lambda raw, *, windows_preferred: "claude-bin")

    def fake_run_subprocess(
        command: list[str],
        *,
        cwd: Path,
        stdin: str | None = None,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        captured.update(
            {
                "command": command,
                "cwd": cwd,
                "stdin": stdin,
                "capture_output": capture_output,
            }
        )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"structured_output": {"summary": "ok"}}),
            stderr="",
        )

    monkeypatch.setattr(generate, "run_subprocess", fake_run_subprocess)

    assert generate.run_claude("prompt", tmp_path, "sonnet", "claude", {"type": "object"}) == {"summary": "ok"}
    assert captured["stdin"] == "prompt"
    assert captured["capture_output"] is True
    assert "--model" in captured["command"]


def test_run_claude_rejects_non_object_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(generate, "resolve_command", lambda raw, *, windows_preferred: "claude-bin")
    monkeypatch.setattr(
        generate,
        "run_subprocess",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout="[]", stderr=""),
    )

    with pytest.raises(CliError, match="not an object payload"):
        generate.run_claude("prompt", tmp_path, "", "claude", {"type": "object"})


def test_run_codex_reads_output_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(generate, "resolve_command", lambda raw, *, windows_preferred: "codex-bin")

    def fake_run_subprocess(command: list[str], *, cwd: Path, stdin: str | None = None, **kwargs: Any) -> None:
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text(json.dumps({"webvtt": "ok"}), encoding="utf-8")

    monkeypatch.setattr(generate, "run_subprocess", fake_run_subprocess)

    assert generate.run_codex("prompt", tmp_path, "gpt", "codex", {"type": "object"}) == {"webvtt": "ok"}


def test_run_chat_api_posts_schema_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("YT_RUBY_SUBS_API_TIMEOUT", "12.5")
    monkeypatch.setattr(generate, "resolve_api_key", lambda: "secret")

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": '{"summary": "ok"}'}}]}).encode("utf-8")

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(generate.urllib.request, "urlopen", fake_urlopen)

    result = generate.run_chat_api(
        "prompt",
        "model",
        "https://openrouter.ai/api/v1/chat/completions",
        {"type": "object", "properties": {"summary": {"type": "string"}}},
    )

    request = captured["request"]
    assert result == {"summary": "ok"}
    assert captured["timeout"] == 12.5
    assert request.get_header("Authorization") == "Bearer secret"
    assert request.get_header("Http-referer") == "https://localhost"
    assert request.get_header("X-openrouter-title") == "yt-ruby-subs"


def test_run_chat_api_wraps_http_and_url_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generate, "resolve_api_key", lambda: "secret")

    def raise_http_error(request: Any, timeout: float) -> None:
        raise urllib.error.HTTPError(
            url="https://example.com",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(b"bad body"),
        )

    monkeypatch.setattr(generate.urllib.request, "urlopen", raise_http_error)
    with pytest.raises(CliError, match="HTTP 400: bad body"):
        generate.run_chat_api("prompt", "", "https://example.com", {"properties": {"summary": {}}})

    monkeypatch.setattr(
        generate.urllib.request,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    with pytest.raises(CliError, match="offline"):
        generate.run_chat_api("prompt", "", "https://example.com", {"properties": {"summary": {}}})


def test_maybe_generate_player_uses_manifest_source_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_subtitle = tmp_path / "source.ja.vtt"
    webvtt = tmp_path / "source.ja.ruby.vtt"
    source_subtitle.write_text("WEBVTT\n", encoding="utf-8")
    webvtt.write_text("WEBVTT\n", encoding="utf-8")
    (tmp_path / "download-manifest.json").write_text(json.dumps({"url": "https://youtu.be/abc"}), encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_generate_player_page(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(generate, "generate_player_page", fake_generate_player_page)

    player_path = generate.maybe_generate_player(
        output_dir=tmp_path,
        stem="source.ja.ruby",
        subtitle_file=source_subtitle,
        webvtt_path=webvtt,
    )

    assert player_path == tmp_path / "source.ja.ruby.player.html"
    assert captured["video_file"] is None
    assert captured["subtitle_file"] == webvtt


def test_run_generation_backend_rejects_unknown_provider(tmp_path: Path) -> None:
    with pytest.raises(CliError, match="unsupported provider"):
        generate.run_generation_backend(
            provider="unknown",
            prompt="prompt",
            schema={},
            subtitle_dir=tmp_path,
            model="",
            api_base_url="",
            codex_bin="codex",
            claude_bin="claude",
        )
