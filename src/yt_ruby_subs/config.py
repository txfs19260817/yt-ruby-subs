import json
from pathlib import Path
from typing import Any

from .errors import CliError

DEFAULTS_NAME = "defaults.json"
BUILTIN_DEFAULTS: dict[str, Any] = {
    "models": {
        "codex": "gpt-5.5",
        "claude": "best",
        "api": "",
    },
    "api_base_url": "https://openrouter.ai/api/v1/chat/completions",
}


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / DEFAULTS_NAME


def load_config(config_path: Path | str | None = None) -> dict[str, Any]:
    base = load_default_config()
    if config_path is None:
        return base

    path = Path(config_path).expanduser()
    if not path.is_file():
        raise CliError(f"config file not found: {path}")
    return _deep_merge(base, read_config_file(path))


def load_default_config() -> dict[str, Any]:
    path = default_config_path()
    if not path.is_file():
        return dict(BUILTIN_DEFAULTS)
    return _deep_merge(BUILTIN_DEFAULTS, read_config_file(path))


def read_config_file(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CliError(f"failed to parse config file {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise CliError(f"config file {path} must contain a JSON object")
    return config


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def default_models(config: dict[str, Any]) -> dict[str, str]:
    models = config.get("models", {})
    if not isinstance(models, dict):
        return {}
    return {str(key): str(value) for key, value in models.items()}


def default_model(provider: str, config: dict[str, Any]) -> str:
    return default_models(config).get(provider, "")


def resolve_model(provider: str, cli_model: str | None, config: dict[str, Any]) -> str:
    if cli_model is not None:
        return cli_model.strip()
    return default_model(provider, config)


def resolve_api_base_url(cli_api_base_url: str | None, config: dict[str, Any]) -> str:
    if cli_api_base_url is not None:
        return cli_api_base_url.strip()
    return str(config.get("api_base_url", ""))
