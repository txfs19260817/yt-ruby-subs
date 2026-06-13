from pathlib import Path

from yt_ruby_subs.cli import build_parser
from yt_ruby_subs.config import default_config_path, load_config, resolve_api_base_url, resolve_model


def test_default_config_path_is_project_root_defaults() -> None:
    assert default_config_path().name == "defaults.json"
    assert default_config_path().parent == Path.cwd()


def test_load_config_reads_explicit_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"models": {"codex": "config-model"}, "api_base_url": "https://config.example/v1/chat"}',
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["models"]["codex"] == "config-model"
    assert config["api_base_url"] == "https://config.example/v1/chat"


def test_cli_values_override_config_values() -> None:
    config = {
        "models": {"codex": "config-model", "api": "config-api-model"},
        "api_base_url": "https://config.example/v1/chat",
    }

    assert resolve_model("codex", "cli-model", config) == "cli-model"
    assert resolve_api_base_url("https://cli.example/v1/chat", config) == "https://cli.example/v1/chat"


def test_config_values_are_used_when_cli_values_are_absent() -> None:
    config = {
        "models": {"codex": "config-model", "api": "config-api-model"},
        "api_base_url": "https://config.example/v1/chat",
    }

    assert resolve_model("codex", None, config) == "config-model"
    assert resolve_api_base_url(None, config) == "https://config.example/v1/chat"


def test_generate_and_run_accept_config_arg() -> None:
    parser = build_parser()

    generate_args = parser.parse_args(["generate", "video.ja.vtt", "--config", "custom.json"])
    run_args = parser.parse_args(["run", "https://example.com/video", "--config", "custom.json"])

    assert generate_args.config == Path("custom.json")
    assert run_args.config == Path("custom.json")
