from yt_ruby_subs.timing import restore_inline_timestamps


def test_restore_inline_timestamps_from_source_caption() -> None:
    source_vtt = """WEBVTT

00:00:15.120 --> 00:00:19.240
昇龍権<00:00:15.120><c>それ</c><00:00:15.320><c>と</c><00:00:15.639><c>同</c><00:00:16.279><c>で</c><00:00:16.560><c>え</c><00:00:17.160><c>有名</c><00:00:17.560><c>な</c><00:00:17.680><c>の</c><00:00:17.760><c>は</c><00:00:18.240><c>やっぱり</c>
"""
    corrected_vtt = """WEBVTT

00:00:15.120 --> 00:00:19.240
それと同格で有名なのはやっぱり
"""

    restored = restore_inline_timestamps(source_vtt, corrected_vtt)

    assert "<00:00:15.120>それ" in restored
    assert "<00:00:15.320>と" in restored
    assert "<00:00:15.639>同" in restored
    assert "<00:00:17.160>有名" in restored


def test_restore_inline_timestamps_inserts_before_ruby_word() -> None:
    reference_vtt = """WEBVTT

00:00:01.000 --> 00:00:02.000
<00:00:01.000>仕事
"""
    ruby_vtt = """WEBVTT

00:00:01.000 --> 00:00:02.000
<ruby>仕事<rt>しごと</rt></ruby>
"""

    restored = restore_inline_timestamps(reference_vtt, ruby_vtt)

    assert "<00:00:01.000><ruby>仕事<rt>しごと</rt></ruby>" in restored


def test_restore_inline_timestamps_moves_existing_timestamp_before_ruby() -> None:
    reference_vtt = """WEBVTT

00:00:01.000 --> 00:00:02.000
<00:00:01.000>仕事
"""
    ruby_vtt = """WEBVTT

00:00:01.000 --> 00:00:02.000
<ruby><00:00:01.000>仕事<rt>しごと</rt></ruby>
"""

    restored = restore_inline_timestamps(reference_vtt, ruby_vtt)

    assert "<00:00:01.000><ruby>仕事<rt>しごと</rt></ruby>" in restored
    assert "<ruby><00:00:01.000>" not in restored
