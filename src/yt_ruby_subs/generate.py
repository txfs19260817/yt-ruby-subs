import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import (
    CORRECTED_OUTPUT_SCHEMA,
    RUBY_OUTPUT_SCHEMA,
    SUMMARY_OUTPUT_SCHEMA,
)
from .errors import CliError
from .models import GenerationResult
from .player import (
    find_source_url_near_subtitle,
    find_video_near_subtitle,
    generate_player_page,
    parse_vtt_cues_from_text,
)
from .process_utils import (
    normalize_newlines,
    parse_json_file,
    resolve_command,
    run_subprocess,
)
from .prompts import build_corrected_prompt, build_ruby_prompt, build_summary_prompt
from .timing import restore_inline_timestamps


def generate_outputs(
    *,
    subtitle_file: Path,
    provider: str,
    model: str,
    api_base_url: str,
    output_dir: Path,
    base_name: str,
    codex_bin: str,
    claude_bin: str,
    prompt_extra: str,
    ocr_reference_file: Path | None = None,
) -> GenerationResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = base_name or f"{subtitle_file.stem}.ruby"
    corrected_path = output_dir / f"{stem}.corrected.vtt"
    webvtt_path = output_dir / f"{stem}.vtt"
    summary_path = output_dir / f"{stem}.summary.txt"

    backend = BackendOptions(
        provider=provider,
        subtitle_dir=subtitle_file.parent,
        model=model,
        api_base_url=api_base_url,
        codex_bin=codex_bin,
        claude_bin=claude_bin,
    )

    source_text = subtitle_file.read_text(encoding="utf-8-sig")
    corrected_text = get_corrected_vtt(
        subtitle_file=subtitle_file,
        corrected_path=corrected_path,
        prompt_extra=prompt_extra,
        ocr_reference_file=ocr_reference_file,
        backend=backend,
    )
    corrected_text = restore_inline_timestamps(source_text, corrected_text)
    write_text_if_changed(corrected_path, corrected_text)
    webvtt_text = get_ruby_vtt(
        corrected_text=corrected_text,
        webvtt_path=webvtt_path,
        backend=backend,
    )
    webvtt_text = restore_inline_timestamps(corrected_text, webvtt_text)
    write_text_if_changed(webvtt_path, webvtt_text)

    for warning in validate_outputs(corrected_text, webvtt_text):
        print(f"warning: {warning}", file=sys.stderr)

    summary = get_summary(
        corrected_text=corrected_text,
        summary_path=summary_path,
        backend=backend,
    )
    player_path = maybe_generate_player(
        output_dir=output_dir,
        stem=stem,
        subtitle_file=subtitle_file,
        webvtt_path=webvtt_path,
    )
    write_generation_manifest(
        output_dir=output_dir,
        stem=stem,
        provider=provider,
        model=model,
        api_base_url=api_base_url,
        subtitle_file=subtitle_file,
        corrected_path=corrected_path,
        webvtt_path=webvtt_path,
        player_path=player_path,
        summary=summary,
        ocr_reference_file=ocr_reference_file,
    )

    return GenerationResult(
        corrected_subtitle_path=corrected_path,
        webvtt_path=webvtt_path,
        provider=provider,
        summary=summary,
        player_path=player_path,
    )


@dataclass(slots=True)
class BackendOptions:
    provider: str
    subtitle_dir: Path
    model: str
    api_base_url: str
    codex_bin: str
    claude_bin: str


def get_corrected_vtt(
    *,
    subtitle_file: Path,
    corrected_path: Path,
    prompt_extra: str,
    ocr_reference_file: Path | None,
    backend: BackendOptions,
) -> str:
    if corrected_path.is_file():
        return read_existing_vtt(corrected_path, "corrected_vtt")

    payload = run_generation_backend(
        provider=backend.provider,
        prompt=build_corrected_prompt(
            subtitle_file, prompt_extra, ocr_reference_file=ocr_reference_file
        ),
        schema=CORRECTED_OUTPUT_SCHEMA,
        subtitle_dir=backend.subtitle_dir,
        model=backend.model,
        api_base_url=backend.api_base_url,
        codex_bin=backend.codex_bin,
        claude_bin=backend.claude_bin,
    )
    corrected_text = normalize_vtt_output(payload, "corrected_vtt")
    if not corrected_text.startswith("WEBVTT"):
        raise CliError("generated corrected subtitle does not start with WEBVTT")
    validate_vtt(corrected_text, "corrected_vtt")
    corrected_path.write_text(corrected_text, encoding="utf-8")
    return corrected_text


def get_ruby_vtt(
    *, corrected_text: str, webvtt_path: Path, backend: BackendOptions
) -> str:
    if webvtt_path.is_file():
        return read_existing_vtt(webvtt_path, "webvtt")

    payload = run_generation_backend(
        provider=backend.provider,
        prompt=build_ruby_prompt(corrected_text),
        schema=RUBY_OUTPUT_SCHEMA,
        subtitle_dir=backend.subtitle_dir,
        model=backend.model,
        api_base_url=backend.api_base_url,
        codex_bin=backend.codex_bin,
        claude_bin=backend.claude_bin,
    )
    webvtt_text = normalize_vtt_output(payload, "webvtt")
    if not webvtt_text.startswith("WEBVTT"):
        raise CliError("generated WebVTT does not start with WEBVTT")
    validate_outputs(corrected_text, webvtt_text)
    webvtt_path.write_text(webvtt_text, encoding="utf-8")
    return webvtt_text


def get_summary(
    *, corrected_text: str, summary_path: Path, backend: BackendOptions
) -> str:
    if summary_path.is_file():
        return summary_path.read_text(encoding="utf-8").strip()

    payload = run_generation_backend(
        provider=backend.provider,
        prompt=build_summary_prompt(corrected_text),
        schema=SUMMARY_OUTPUT_SCHEMA,
        subtitle_dir=backend.subtitle_dir,
        model=backend.model,
        api_base_url=backend.api_base_url,
        codex_bin=backend.codex_bin,
        claude_bin=backend.claude_bin,
    )
    summary = str(payload.get("summary", "")).strip()
    summary_path.write_text(summary + "\n", encoding="utf-8")
    return summary


def read_existing_vtt(path: Path, label: str) -> str:
    text = normalize_newlines(path.read_text(encoding="utf-8-sig")).strip() + "\n"
    if not text.startswith("WEBVTT"):
        raise CliError(f"existing {label} does not start with WEBVTT: {path}")
    return text


def write_text_if_changed(path: Path, text: str) -> None:
    if (
        path.is_file()
        and normalize_newlines(path.read_text(encoding="utf-8-sig")).strip() + "\n"
        == text
    ):
        return
    path.write_text(text, encoding="utf-8")


def run_generation_backend(
    *,
    provider: str,
    prompt: str,
    schema: dict[str, Any],
    subtitle_dir: Path,
    model: str,
    api_base_url: str,
    codex_bin: str,
    claude_bin: str,
) -> dict[str, Any]:
    if provider == "codex":
        return run_codex(prompt, subtitle_dir, model, codex_bin, schema)
    if provider == "claude":
        return run_claude(prompt, subtitle_dir, model, claude_bin, schema)
    if provider == "api":
        return run_chat_api(prompt, model, api_base_url, schema)
    raise CliError(f"unsupported provider: {provider}")


def normalize_vtt_output(payload: dict[str, Any], key: str) -> str:
    return normalize_newlines(payload[key]).strip() + "\n"


def maybe_generate_player(
    *, output_dir: Path, stem: str, subtitle_file: Path, webvtt_path: Path
) -> Path | None:
    sibling_video = find_video_near_subtitle(subtitle_file)
    if sibling_video is None and not find_source_url_near_subtitle(webvtt_path):
        return None

    player_path = output_dir / f"{stem}.player.html"
    generate_player_page(
        video_file=sibling_video,
        subtitle_file=webvtt_path,
        html_path=player_path,
    )
    return player_path


def write_generation_manifest(
    *,
    output_dir: Path,
    stem: str,
    provider: str,
    model: str,
    api_base_url: str,
    subtitle_file: Path,
    corrected_path: Path,
    webvtt_path: Path,
    player_path: Path | None,
    summary: object,
    ocr_reference_file: Path | None,
) -> None:
    manifest = {
        "provider": provider,
        "model": model or None,
        "api_base_url": api_base_url if provider == "api" else None,
        "subtitle_file": str(subtitle_file),
        "corrected_subtitle_path": str(corrected_path),
        "webvtt_path": str(webvtt_path),
        "player_path": str(player_path) if player_path else None,
        "summary": summary,
        "ocr_reference_file": str(ocr_reference_file) if ocr_reference_file else None,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (output_dir / f"{stem}.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def validate_outputs(corrected_text: str, webvtt_text: str) -> list[str]:
    """Sanity-check the model's two WebVTT outputs; raise on empty, warn on the rest."""
    corrected_cues, warnings = validate_vtt(corrected_text, "corrected_vtt")
    ruby_cues, ruby_warnings = validate_vtt(webvtt_text, "webvtt")
    warnings.extend(ruby_warnings)

    if len(corrected_cues) != len(ruby_cues):
        warnings.append(
            f"cue count differs (corrected={len(corrected_cues)}, ruby={len(ruby_cues)}); "
            "ruby output may have dropped or merged lines"
        )
        return warnings

    mismatched = sum(
        1
        for corrected, ruby in zip(corrected_cues, ruby_cues)
        if strip_to_plain(str(corrected["text"])) != strip_to_plain(str(ruby["text"]))
    )
    if mismatched:
        warnings.append(
            f"{mismatched} ruby cue(s) differ in text from the corrected transcript"
        )
    return warnings


def validate_vtt(text: str, label: str) -> tuple[list[dict[str, object]], list[str]]:
    cues = parse_vtt_cues_from_text(text)
    if not cues:
        raise CliError(f"{label} parsed to zero subtitle cues")

    warnings: list[str] = []
    if empty := sum(1 for cue in cues if not str(cue["text"]).strip()):
        warnings.append(f"{label}: {empty} empty cue(s)")
    if bad := sum(
        1 for cue in cues if not 0 <= float(cue["start"]) < float(cue["end"])
    ):
        warnings.append(f"{label}: {bad} cue(s) with non-positive or negative duration")
    if disordered := sum(
        1 for a, b in zip(cues, cues[1:]) if float(b["start"]) < float(a["start"])
    ):
        warnings.append(f"{label}: {disordered} cue(s) out of chronological order")
    return cues, warnings


def strip_to_plain(text: str) -> str:
    """Reduce a cue to bare characters so corrected vs. ruby text can be compared."""
    text = re.sub(r"<rt>.*?</rt>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", "", text)


def run_codex(
    prompt: str, cwd: Path, model: str, codex_bin: str, schema: dict[str, Any]
) -> dict[str, Any]:
    codex = resolve_command(
        codex_bin, windows_preferred=("codex.cmd", "codex.exe", "codex")
    )

    with tempfile.TemporaryDirectory(prefix="yt-ruby-subs-codex-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        schema_path = temp_dir / "schema.json"
        output_path = temp_dir / "result.json"
        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        command = [
            codex,
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "-C",
            str(cwd),
            "--output-schema",
            str(schema_path),
            "-o",
            str(output_path),
        ]
        if model:
            command.extend(["--model", model])
        command.append("-")

        run_subprocess(command, cwd=cwd, stdin=prompt)
        if not output_path.is_file():
            raise CliError("codex did not produce an output file")

        return parse_json_file(output_path)


def run_claude(
    prompt: str, cwd: Path, model: str, claude_bin: str, schema: dict[str, Any]
) -> dict[str, Any]:
    claude = resolve_command(
        claude_bin, windows_preferred=("claude.exe", "claude.cmd", "claude")
    )
    command = [
        claude,
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema, ensure_ascii=False),
        "--tools=",
    ]
    if model:
        command.extend(["--model", model])

    completed = run_subprocess(command, cwd=cwd, stdin=prompt, capture_output=True)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CliError(f"failed to parse Claude output as JSON: {exc}") from exc

    if isinstance(payload, dict):
        structured = payload.get("structured_output")
        if isinstance(structured, dict):
            return structured
        return payload

    raise CliError("Claude returned JSON, but not an object payload")


def run_chat_api(
    prompt: str, model: str, api_base_url: str, schema: dict[str, Any]
) -> dict[str, Any]:
    api_key = resolve_api_key()
    body: dict[str, Any] = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You convert subtitle files into corrected WebVTT and ruby WebVTT. "
                    "Return structured JSON only."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.2,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "yt_ruby_subs_response",
                "strict": True,
                "schema": schema,
            },
        },
    }
    if model:
        body["model"] = model

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if "openrouter.ai" in api_base_url:
        headers["HTTP-Referer"] = os.getenv(
            "YT_RUBY_SUBS_HTTP_REFERER", "https://localhost"
        )
        headers["X-OpenRouter-Title"] = os.getenv(
            "YT_RUBY_SUBS_OPENROUTER_TITLE", "yt-ruby-subs"
        )

    request = urllib.request.Request(
        api_base_url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    timeout_seconds = float(os.getenv("YT_RUBY_SUBS_API_TIMEOUT", "600"))

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise CliError(f"chat API request failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise CliError(f"chat API request failed: {exc.reason}") from exc

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise CliError(f"failed to parse chat API response as JSON: {exc}") from exc

    return parse_chat_api_payload(payload, tuple(schema["properties"]))


def resolve_api_key() -> str:
    for env_name in ("YT_RUBY_SUBS_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        value = os.getenv(env_name, "").strip()
        if value:
            return value
    raise CliError(
        "chat API key not found; set YT_RUBY_SUBS_API_KEY or OPENROUTER_API_KEY "
        "(or OPENAI_API_KEY for another OpenAI-compatible endpoint)"
    )


def parse_chat_api_payload(
    payload: Any, expected_keys: tuple[str, ...]
) -> dict[str, Any]:
    if isinstance(payload, dict) and all(key in payload for key in expected_keys):
        return payload

    if not isinstance(payload, dict):
        raise CliError("chat API returned JSON, but not an object payload")

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise CliError("chat API response does not contain choices")

    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise CliError("chat API response choice does not contain a message")

    parsed = message.get("parsed")
    if isinstance(parsed, dict):
        return parsed

    content = message.get("content")
    content_text = extract_message_text(content)
    if not content_text:
        raise CliError("chat API response message content is empty")

    try:
        candidate = json.loads(content_text)
    except json.JSONDecodeError:
        candidate = json.loads(extract_json_object(content_text))

    if not isinstance(candidate, dict):
        raise CliError("chat API structured output is not a JSON object")
    return candidate


def extract_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "".join(parts).strip()
    return ""


def extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise CliError("chat API response does not contain a JSON object")
    return stripped[start : end + 1]
