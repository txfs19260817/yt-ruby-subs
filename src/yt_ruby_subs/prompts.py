import textwrap
from pathlib import Path


def build_corrected_prompt(
    subtitle_file: Path,
    prompt_extra: str,
    *,
    ocr_reference_file: Path | None = None,
) -> str:
    content = subtitle_file.read_text(encoding="utf-8-sig")
    ocr_reference = read_ocr_reference(ocr_reference_file)
    instructions = textwrap.dedent(
        """
        You prepare Japanese subtitles for shadowing (read-aloud / follow-along)
        practice. Convert the subtitle file below into one corrected WebVTT output.

        Output "corrected_vtt": a cleaned plain-text transcript.
          - Start the file with the line WEBVTT.
          - The source is often a YouTube auto-caption "rolling" track where each
            cue repeats the previous line plus a few new words. Collapse those
            duplicates so every spoken phrase appears exactly once, in order.
          - Fix obvious speech-recognition errors, including homophones and
            mis-segmented words, using the surrounding sentence as context.
          - Normalize digits read aloud (e.g. write 0を1にする, not 01する).
          - Keep the text natural Japanese. Do NOT translate or add commentary.
          - Re-segment for shadowing: prefer one short phrase, or at most two
            short lines, per cue. Break on natural phrase boundaries, not on raw
            ASR chunk edges. Short, readable cues beat long merged sentences.
          - Keep timing aligned with the audio. Reuse the source start/end times;
            when you merge or split cues, keep the new boundaries inside the span
            of the originals so subtitles still track the speech.
          - Preserve inline word-level timestamp tags like <00:00:12.345> when the
            source has them and they still sit between the right words; they drive
            per-word highlighting in the player. Drop only the ones you break.
          - Use OCR as a correction reference when an OCR block is provided. OCR
            may contain hard subtitles from the video image; prefer it over ASR
            for misheard words, but ignore obvious OCR noise.
          - Do NOT add ruby/furigana in this output.

        Rules:
          - Return JSON only, matching the provided schema. No Markdown fences.
          - Do not run shell commands or inspect the environment; work only from
            the subtitle text below.
          - Cover the WHOLE file start to finish. Never drop, truncate, or
            summarize cues — every part of the audio must remain subtitled.
        """
    ).strip()

    if prompt_extra:
        instructions += f"\n\nAdditional instruction:\n{prompt_extra.strip()}"

    prompt = (
        f"{instructions}\n\n"
        f"Source subtitle filename: {subtitle_file.name}\n\n"
        "<subtitle_file>\n"
        f"{content}\n"
        "</subtitle_file>\n"
    )
    if ocr_reference:
        prompt += f"\n<ocr_reference>\n{ocr_reference}\n</ocr_reference>\n"
    return prompt


def build_ruby_prompt(corrected_vtt: str) -> str:
    instructions = textwrap.dedent(
        """
        Add ruby/furigana markup to the corrected WebVTT below.

        Output "webvtt": the corrected WebVTT with ruby furigana added.
          - Start with WEBVTT and reuse the corrected cues, timing and line breaks
            exactly. Same number of cues, same plain text. Only ruby markup is added.
          - Annotate every kanji word with <ruby>漢字<rt>かんじ</rt></ruby>.
            Group whole words (e.g. <ruby>仕事<rt>しごと</rt></ruby>), not single
            characters, so readings are natural. Leave kana untouched.
          - For an uncertain reading, pick the most likely one.
          - Keep inline word-level timestamp tags like <00:00:12.345> in the same positions.

        Rules:
          - Return JSON only, matching the provided schema. No Markdown fences.
          - Do not run shell commands or inspect the environment.
        """
    ).strip()
    return f"{instructions}\n\n<corrected_vtt>\n{corrected_vtt}\n</corrected_vtt>\n"


def build_summary_prompt(corrected_vtt: str) -> str:
    instructions = textwrap.dedent(
        """
        Write one short sentence describing the clip represented by the corrected WebVTT below.

        Output "summary": one short sentence in Japanese or English, for display only.

        Rules:
          - Return JSON only, matching the provided schema. No Markdown fences.
          - Do not run shell commands or inspect the environment.
        """
    ).strip()
    return f"{instructions}\n\n<corrected_vtt>\n{corrected_vtt}\n</corrected_vtt>\n"


def build_prompt(subtitle_file: Path, prompt_extra: str) -> str:
    return build_corrected_prompt(subtitle_file, prompt_extra)


def read_ocr_reference(path: Path | None) -> str:
    if path is None:
        return ""
    return path.read_text(encoding="utf-8-sig").strip()
