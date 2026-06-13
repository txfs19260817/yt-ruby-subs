import argparse
import sys
from pathlib import Path

from .config import load_config, resolve_api_base_url, resolve_model
from .download import download_with_yt_dlp
from .errors import CliError
from .generate import generate_outputs
from .models import DownloadResult, GenerationResult, PlayerResult
from .player import generate_player_page


def main(argv: list[str] | None = None) -> int:
    configure_standard_streams()
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        return args.func(args)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130


def configure_standard_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-ruby-subs",
        description=(
            "Download videos and subtitles with yt-dlp, then ask Codex or Claude Code "
            "to generate ruby-annotated WebVTT files."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser(
        "download",
        help="Download a video and matching subtitles with yt-dlp.",
    )
    add_download_args(download_parser)
    download_parser.set_defaults(func=handle_download)

    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate ruby WebVTT from an existing subtitle file.",
    )
    add_generate_args(generate_parser)
    generate_parser.set_defaults(func=handle_generate)

    run_parser = subparsers.add_parser(
        "run",
        help="Download first, then generate ruby WebVTT from the selected subtitle file.",
    )
    add_download_args(run_parser)
    add_generate_args(run_parser, include_input=False)
    run_parser.set_defaults(func=handle_run)

    player_parser = subparsers.add_parser(
        "player",
        help="Generate a local HTML player with clickable subtitles.",
    )
    add_player_args(player_parser)
    player_parser.set_defaults(func=handle_player)

    return parser


def add_download_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("url", help="Video URL to pass to yt-dlp.")
    parser.add_argument(
        "--lang",
        default="ja",
        help="Subtitle language expression for yt-dlp --sub-langs. Default: ja",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("downloads"),
        help="Root directory for downloaded files. Default: ./downloads",
    )
    parser.add_argument(
        "--job-name",
        default="",
        help="Optional suffix for the download folder name.",
    )
    parser.add_argument(
        "--no-video",
        action="store_true",
        help="Skip the media download and fetch subtitles/metadata only.",
    )
    parser.add_argument(
        "--subtitle-format",
        default="vtt/srt/best",
        help="Subtitle format preference passed to yt-dlp --sub-format.",
    )
    parser.add_argument(
        "--yt-dlp-bin",
        default="yt-dlp",
        help="yt-dlp executable to use. Default: yt-dlp",
    )


def add_generate_args(parser: argparse.ArgumentParser, *, include_input: bool = True) -> None:
    if include_input:
        parser.add_argument(
            "subtitle_file",
            type=Path,
            help="Existing subtitle file to transform.",
        )

    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Config file to load. Default: ./defaults.json",
    )
    parser.add_argument(
        "--provider",
        choices=("codex", "claude", "api"),
        default="codex",
        help="Backend to use for subtitle conversion. Default: codex",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model override passed to the selected backend. Overrides the config file.",
    )
    parser.add_argument(
        "--api-base-url",
        default=None,
        help="OpenAI-compatible chat completions endpoint for --provider api. Overrides the config file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for generated subtitle outputs. Defaults to the subtitle file directory.",
    )
    parser.add_argument(
        "--base-name",
        default="",
        help="Base file name for outputs. Default: <subtitle-stem>.ruby",
    )
    parser.add_argument(
        "--codex-bin",
        default="codex",
        help="Codex executable to use. Default: codex",
    )
    parser.add_argument(
        "--claude-bin",
        default="claude",
        help="Claude executable to use. Default: claude",
    )
    parser.add_argument(
        "--prompt-extra",
        default="",
        help="Extra instruction appended to the subtitle conversion prompt.",
    )


def add_player_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "video_file",
        type=Path,
        help="Video file to play in the browser.",
    )
    parser.add_argument(
        "subtitle_file",
        type=Path,
        help="Subtitle file to load in the browser.",
    )
    parser.add_argument(
        "--output-html",
        type=Path,
        default=None,
        help="Output HTML file. Defaults to <subtitle-stem>.player.html next to the subtitle file.",
    )


def handle_download(args: argparse.Namespace) -> int:
    result = download_with_yt_dlp(
        url=args.url,
        lang=args.lang,
        output_root=args.output_root,
        job_name=args.job_name,
        no_video=args.no_video,
        subtitle_format=args.subtitle_format,
        yt_dlp_bin=args.yt_dlp_bin,
    )
    print_download_summary(result)
    return 0


def handle_generate(args: argparse.Namespace) -> int:
    subtitle_file = args.subtitle_file.resolve()
    if not subtitle_file.is_file():
        raise CliError(f"subtitle file not found: {subtitle_file}")

    config = load_config(args.config)
    generation = generate_from_args(
        args,
        subtitle_file=subtitle_file,
        default_output_dir=subtitle_file.parent,
        config=config,
    )
    print_generation_summary(generation)
    return 0


def handle_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    download_result = download_with_yt_dlp(
        url=args.url,
        lang=args.lang,
        output_root=args.output_root,
        job_name=args.job_name,
        no_video=args.no_video,
        subtitle_format=args.subtitle_format,
        yt_dlp_bin=args.yt_dlp_bin,
    )
    print_download_summary(download_result)

    if download_result.selected_subtitle is None:
        raise CliError("no subtitle file was downloaded for the requested language")

    generation = generate_from_args(
        args,
        subtitle_file=download_result.selected_subtitle,
        default_output_dir=download_result.work_dir,
        config=config,
    )
    print_generation_summary(generation)
    return 0


def generate_from_args(
    args: argparse.Namespace,
    *,
    subtitle_file: Path,
    default_output_dir: Path,
    config: dict[str, object],
) -> GenerationResult:
    output_dir = args.output_dir.resolve() if args.output_dir else default_output_dir
    return generate_outputs(
        subtitle_file=subtitle_file,
        provider=args.provider,
        model=resolve_model(args.provider, args.model, config),
        api_base_url=resolve_api_base_url(args.api_base_url, config),
        output_dir=output_dir,
        base_name=args.base_name,
        codex_bin=args.codex_bin,
        claude_bin=args.claude_bin,
        prompt_extra=args.prompt_extra,
    )


def handle_player(args: argparse.Namespace) -> int:
    video_file = args.video_file.resolve()
    subtitle_file = args.subtitle_file.resolve()
    if not video_file.is_file():
        raise CliError(f"video file not found: {video_file}")
    if not subtitle_file.is_file():
        raise CliError(f"subtitle file not found: {subtitle_file}")

    html_path = args.output_html.resolve() if args.output_html else subtitle_file.with_suffix(".player.html")
    player = generate_player_page(
        video_file=video_file,
        subtitle_file=subtitle_file,
        html_path=html_path,
    )
    print_player_summary(player)
    return 0


def print_download_summary(result: DownloadResult) -> None:
    print(f"download_dir: {result.work_dir}")
    print(f"videos: {len(result.video_files)}")
    for path in result.video_files:
        print(f"  video: {path}")
    print(f"subtitles: {len(result.subtitle_files)}")
    for path in result.subtitle_files:
        marker = " [selected]" if result.selected_subtitle == path else ""
        print(f"  subtitle: {path}{marker}")


def print_generation_summary(result: GenerationResult) -> None:
    print(f"provider: {result.provider}")
    print(f"corrected_vtt: {result.corrected_subtitle_path}")
    print(f"webvtt: {result.webvtt_path}")
    if result.player_path:
        print(f"player: {result.player_path}")
    if result.summary:
        print(f"summary: {result.summary}")


def print_player_summary(result: PlayerResult) -> None:
    print(f"player: {result.html_path}")
    if result.video_path:
        print(f"video: {result.video_path}")
    print(f"subtitle: {result.subtitle_path}")
