"""Transcript export builders: TXT, SRT, VTT, JSON, CSV and DOCX.

Every builder works from the same normalized ``segments`` list so a transcript
can always be re-exported into another format without loss of timing data.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from typing import Any, Callable

from xml.sax.saxutils import escape as xml_escape

Segment = dict[str, Any]


def format_timestamp(seconds: float, decimal_separator: str = ",") -> str:
    """Format seconds as ``HH:MM:SS,mmm`` (SRT) or ``HH:MM:SS.mmm`` (VTT)."""
    if seconds is None or seconds < 0:
        seconds = 0.0
    milliseconds = int(round(float(seconds) * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return (
        f"{hours:02d}:{minutes:02d}:{secs:02d}"
        f"{decimal_separator}{milliseconds:03d}"
    )


def format_clock(seconds: float) -> str:
    """Short ``M:SS`` / ``H:MM:SS`` style used in the UI and TXT headers."""
    if not seconds:
        return "0:00"
    total = int(round(float(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _segment_text(segment: Segment) -> str:
    return str(segment.get("text", "")).strip()


def segments_to_text(segments: list[Segment], paragraph: bool = True) -> str:
    chunks = [_segment_text(segment) for segment in segments]
    chunks = [chunk for chunk in chunks if chunk]
    if paragraph:
        return " ".join(chunks).strip()
    return "\n".join(chunks).strip()


def segments_to_timestamped_text(segments: list[Segment]) -> str:
    lines = []
    for segment in segments:
        text = _segment_text(segment)
        if not text:
            continue
        lines.append(f"[{format_clock(segment.get('start', 0))}] {text}")
    return "\n".join(lines)


def _timed_export_items(segments: list[Segment]):
    """Yield word timing rows, falling back to a segment when words are absent."""
    for segment_index, segment in enumerate(segments, start=1):
        words = segment.get("words") or []
        if words:
            for word_index, word in enumerate(words, start=1):
                if not isinstance(word, dict):
                    continue
                text = str(word.get("word", "")).strip()
                if not text:
                    continue
                start = word.get("start", segment.get("start", 0.0))
                end = word.get("end", start)
                yield segment_index, word_index, start, end, text, word.get("probability")
        else:
            text = _segment_text(segment)
            if text:
                start = segment.get("start", 0.0)
                yield segment_index, 0, start, segment.get("end", start), text, None


def segments_to_word_timestamped_text(segments: list[Segment]) -> str:
    return "\n".join(
        f"[{format_timestamp(start, '.')} --> {format_timestamp(end, '.')}] {text}"
        for _, _, start, end, text, _ in _timed_export_items(segments)
    )


def segments_to_word_srt(segments: list[Segment]) -> str:
    blocks = []
    for index, (_, _, start, end, text, _) in enumerate(_timed_export_items(segments), start=1):
        blocks.append(
            f"{index}\n{format_timestamp(start, ',')} --> {format_timestamp(end, ',')}\n{text}\n"
        )
    return "\n".join(blocks).strip() + ("\n" if blocks else "")


def segments_to_word_vtt(segments: list[Segment]) -> str:
    lines = ["WEBVTT", ""]
    for _, _, start, end, text, _ in _timed_export_items(segments):
        lines.extend((f"{format_timestamp(start, '.')} --> {format_timestamp(end, '.')}", text, ""))
    return "\n".join(lines).strip() + "\n"


def segments_to_word_csv(segments: list[Segment]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["segment_index", "word_index", "start", "end", "start_seconds", "end_seconds", "word", "probability"])
    for segment_index, word_index, start, end, text, probability in _timed_export_items(segments):
        writer.writerow([
            segment_index,
            word_index or "",
            format_timestamp(start, "."),
            format_timestamp(end, "."),
            round(float(start), 3),
            round(float(end), 3),
            text,
            probability if probability is not None else "",
        ])
    return buffer.getvalue()


def segments_to_word_docx(title: str, segments: list[Segment]) -> bytes:
    paragraphs = [_docx_paragraph(title, bold=True, size=32), _docx_paragraph("", size=22)]
    for _, _, start, end, text, _ in _timed_export_items(segments):
        stamp = f"[{format_timestamp(start, '.')} --> {format_timestamp(end, '.')}] {text}"
        paragraphs.append(_docx_paragraph(stamp, size=22))
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>" + "".join(paragraphs)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def segments_to_srt(segments: list[Segment]) -> str:
    blocks = []
    index = 0
    for segment in segments:
        text = _segment_text(segment)
        if not text:
            continue
        index += 1
        start = format_timestamp(segment.get("start", 0.0), ",")
        end = format_timestamp(segment.get("end", segment.get("start", 0.0) + 1), ",")
        blocks.append(f"{index}\n{start} --> {end}\n{text}\n")
    return "\n".join(blocks).strip() + ("\n" if blocks else "")


def segments_to_vtt(segments: list[Segment]) -> str:
    lines = ["WEBVTT", ""]
    for segment in segments:
        text = _segment_text(segment)
        if not text:
            continue
        start = format_timestamp(segment.get("start", 0.0), ".")
        end = format_timestamp(segment.get("end", segment.get("start", 0.0) + 1), ".")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def segments_to_csv(segments: list[Segment], include_words: bool = False) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["index", "start", "end", "start_seconds", "end_seconds", "text"])
    for index, segment in enumerate(segments, start=1):
        writer.writerow(
            [
                index,
                format_timestamp(segment.get("start", 0.0), "."),
                format_timestamp(segment.get("end", 0.0), "."),
                round(float(segment.get("start", 0.0)), 3),
                round(float(segment.get("end", 0.0)), 3),
                _segment_text(segment),
            ]
        )
    return buffer.getvalue()


def transcript_to_json(metadata: dict[str, Any], segments: list[Segment], text: str) -> str:
    payload = {
        "application": "HawkTranscriber",
        "metadata": metadata,
        "text": text,
        "segments": segments,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def segments_to_docx(title: str, segments: list[Segment]) -> bytes:
    """Build a minimal but valid Word document from the transcript."""
    paragraphs = [
        _docx_paragraph(title, bold=True, size=32),
        _docx_paragraph("", size=22),
    ]
    for segment in segments:
        text = _segment_text(segment)
        if not text:
            continue
        stamp = format_clock(segment.get("start", 0.0))
        paragraphs.append(
            _docx_paragraph(f"[{stamp}] {text}", size=22)
        )

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(paragraphs)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>'
        + "</w:body></w:document>"
    )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )

    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _docx_paragraph(text: str, bold: bool = False, size: int = 22) -> str:
    safe = xml_escape(text)
    run_props = f'<w:rPr><w:sz w:val="{size}"/>'
    if bold:
        run_props += "<w:b/>"
    run_props += "</w:rPr>"
    return (
        "<w:p><w:r>"
        f"{run_props}"
        f'<w:t xml:space="preserve">{safe}</w:t>'
        "</w:r></w:p>"
    )


EXPORTERS: dict[str, dict[str, Any]] = {
    "txt": {
        "label": "Plain text",
        "extension": "txt",
        "mime": "text/plain; charset=utf-8",
    },
    "srt": {
        "label": "SubRip subtitles",
        "extension": "srt",
        "mime": "application/x-subrip; charset=utf-8",
    },
    "vtt": {
        "label": "WebVTT subtitles",
        "extension": "vtt",
        "mime": "text/vtt; charset=utf-8",
    },
    "json": {
        "label": "Structured JSON",
        "extension": "json",
        "mime": "application/json; charset=utf-8",
    },
    "csv": {
        "label": "Segments CSV",
        "extension": "csv",
        "mime": "text/csv; charset=utf-8",
    },
    "docx": {
        "label": "Word document",
        "extension": "docx",
        "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
}


def build_export(
    fmt: str,
    segments: list[Segment],
    text: str,
    metadata: dict[str, Any],
    word_level: bool = False,
) -> tuple[bytes, str, str]:
    """Return ``(payload, extension, mime)`` for a given export format."""
    fmt = (fmt or "").lower().strip()
    if fmt not in EXPORTERS:
        raise ValueError(f"Unsupported export format: {fmt!r}")

    meta = EXPORTERS[fmt]
    if fmt == "txt":
        payload = (
            segments_to_word_timestamped_text(segments)
            if word_level
            else segments_to_timestamped_text(segments)
        ) or text
        return payload.encode("utf-8"), meta["extension"], meta["mime"]
    if fmt == "srt":
        payload = segments_to_word_srt(segments) if word_level else segments_to_srt(segments)
        return payload.encode("utf-8"), meta["extension"], meta["mime"]
    if fmt == "vtt":
        payload = segments_to_word_vtt(segments) if word_level else segments_to_vtt(segments)
        return payload.encode("utf-8"), meta["extension"], meta["mime"]
    if fmt == "json":
        body = transcript_to_json(metadata, segments, text)
        return body.encode("utf-8"), meta["extension"], meta["mime"]
    if fmt == "csv":
        payload = segments_to_word_csv(segments) if word_level else segments_to_csv(segments)
        return payload.encode("utf-8"), meta["extension"], meta["mime"]
    if fmt == "docx":
        title = metadata.get("title") or "Transcript"
        payload = segments_to_word_docx(title, segments) if word_level else segments_to_docx(title, segments)
        return payload, meta["extension"], meta["mime"]
    raise ValueError(f"Unsupported export format: {fmt!r}")
