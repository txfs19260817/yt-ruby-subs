import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .player import TIMECODE_RE, timestamp_to_seconds
from .process_utils import normalize_newlines

INLINE_TIMESTAMP_RE = re.compile(r"<(?P<timestamp>\d{2}:\d{2}(?::\d{2})?\.\d{3})>")
RUBY_TIMESTAMP_RE = re.compile(r"(<ruby\b[^>]*>)<(?P<timestamp>\d{2}:\d{2}(?::\d{2})?\.\d{3})>")
RT_RE = re.compile(r"<rt\b[^>]*>.*?</rt>", re.DOTALL)
HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class TimedToken:
    timestamp: str
    start: float
    text: str


def restore_inline_timestamps(reference_vtt: str, target_vtt: str) -> str:
    """Copy word-level timestamp tags from a reference VTT into matching target cues."""
    timed_tokens = extract_timed_tokens(reference_vtt)
    if not timed_tokens:
        return normalize_newlines(target_vtt).strip() + "\n"

    return transform_cue_text(
        target_vtt,
        lambda start, end, text: add_timestamps_to_cue_text(
            text,
            [token for token in timed_tokens if start <= token.start < end],
        ),
    )


def extract_timed_tokens(vtt_text: str) -> list[TimedToken]:
    tokens: list[TimedToken] = []
    seen: set[tuple[str, str]] = set()
    for block in split_vtt_blocks(vtt_text):
        cue = parse_block(block)
        if cue is None:
            continue
        for token in extract_tokens_from_cue_text(cue["text"]):
            key = (token.timestamp, token.text)
            if key in seen:
                continue
            seen.add(key)
            tokens.append(token)
    return sorted(tokens, key=lambda token: token.start)


def extract_tokens_from_cue_text(text: str) -> list[TimedToken]:
    matches = list(INLINE_TIMESTAMP_RE.finditer(text))
    tokens: list[TimedToken] = []
    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        token_text = plain_visible_text(text[match.end() : next_start])
        if token_text:
            timestamp = match.group("timestamp")
            tokens.append(
                TimedToken(
                    timestamp=timestamp,
                    start=timestamp_to_seconds(timestamp),
                    text=token_text,
                )
            )
    return tokens


def transform_cue_text(vtt_text: str, replacer) -> str:
    transformed_blocks: list[str] = []
    for block in split_vtt_blocks(vtt_text):
        cue = parse_block(block)
        if cue is None:
            transformed_blocks.append(block)
            continue

        lines = block.split("\n")
        new_text = replacer(cue["start"], cue["end"], cue["text"])
        transformed_blocks.append("\n".join([*lines[: cue["text_start_line"]], *new_text.split("\n")]))
    return "\n\n".join(transformed_blocks).strip() + "\n"


def split_vtt_blocks(vtt_text: str) -> list[str]:
    normalized = normalize_newlines(vtt_text).strip()
    if not normalized:
        return []
    return re.split(r"\n\s*\n", normalized)


def parse_block(block: str) -> dict[str, object] | None:
    lines = block.split("\n")
    if not lines or lines[0].startswith("WEBVTT"):
        return None

    timing_line_index = None
    if "-->" in lines[0]:
        timing_line_index = 0
    elif len(lines) >= 2 and "-->" in lines[1]:
        timing_line_index = 1
    if timing_line_index is None:
        return None

    match = TIMECODE_RE.match(lines[timing_line_index])
    if not match:
        return None

    text_start_line = timing_line_index + 1
    return {
        "start": timestamp_to_seconds(match.group("start")),
        "end": timestamp_to_seconds(match.group("end")),
        "text": "\n".join(lines[text_start_line:]),
        "text_start_line": text_start_line,
    }


def add_timestamps_to_cue_text(text: str, timed_tokens: list[TimedToken]) -> str:
    text = move_timestamps_before_ruby(text)
    if not timed_tokens or INLINE_TIMESTAMP_RE.search(text):
        return text

    source_text = ""
    token_starts: list[tuple[TimedToken, int]] = []
    for token in timed_tokens:
        token_text = plain_visible_text(token.text)
        if not token_text:
            continue
        token_starts.append((token, len(source_text)))
        source_text += token_text

    target_text = plain_visible_text(text)
    if not source_text or not target_text:
        return text

    source_to_target = build_equal_index_map(source_text, target_text)
    insertions: list[tuple[int, str]] = []
    seen_positions: set[int] = set()
    for token, source_index in token_starts:
        target_index = source_to_target.get(source_index)
        if target_index is None:
            continue
        position = visible_index_to_markup_position(text, target_index)
        if position in seen_positions:
            continue
        seen_positions.add(position)
        insertions.append((position, f"<{token.timestamp}>"))

    return insert_at_positions(text, insertions)


def plain_visible_text(text: str) -> str:
    text = INLINE_TIMESTAMP_RE.sub("", text)
    text = RT_RE.sub("", text)
    text = HTML_TAG_RE.sub("", text)
    return re.sub(r"\s+", "", text)


def move_timestamps_before_ruby(text: str) -> str:
    return RUBY_TIMESTAMP_RE.sub(lambda match: f"<{match.group('timestamp')}>{match.group(1)}", text)


def build_equal_index_map(source_text: str, target_text: str) -> dict[int, int]:
    matcher = SequenceMatcher(a=source_text, b=target_text, autojunk=False)
    mapping: dict[int, int] = {}
    for tag, source_start, source_end, target_start, _target_end in matcher.get_opcodes():
        if tag != "equal":
            continue
        for offset in range(source_end - source_start):
            mapping[source_start + offset] = target_start + offset
    return mapping


def visible_index_to_markup_position(text: str, target_index: int) -> int:
    visible_index = 0
    index = 0
    ruby_start: int | None = None
    while index < len(text):
        if text.startswith("<ruby", index):
            ruby_start = index
            index = skip_tag(text, index)
            continue
        if text.startswith("</ruby", index):
            ruby_start = None
            index = skip_tag(text, index)
            continue
        if text.startswith("<rt", index):
            index = skip_rt(text, index)
            continue
        if text[index] == "<":
            index = skip_tag(text, index)
            continue
        if not text[index].isspace():
            if visible_index == target_index:
                return ruby_start if ruby_start is not None else index
            visible_index += 1
        index += 1
    return len(text)


def skip_tag(text: str, index: int) -> int:
    end = text.find(">", index)
    return len(text) if end == -1 else end + 1


def skip_rt(text: str, index: int) -> int:
    end = text.find("</rt>", index)
    return skip_tag(text, index) if end == -1 else end + len("</rt>")


def insert_at_positions(text: str, insertions: list[tuple[int, str]]) -> str:
    result = text
    for position, tag in sorted(insertions, reverse=True):
        result = f"{result[:position]}{tag}{result[position:]}"
    return result
