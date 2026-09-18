from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedRelease:
    resolution: str | None
    source: str | None
    codec: str | None
    audio: str | None
    channels: str | None
    hdr: bool
    dolby_vision: bool
    atmos: bool
    multi: bool
    vf: bool
    vfi: bool
    vff: bool
    vostfr: bool
    audio_description: bool
    size_gb: float | None


DEFAULTS = {
    "smart_filter_enabled": True,
    "smart_quality_mode": "prefer-4k",
    "smart_prefer_x265": True,
    "smart_require_x265": False,
    "smart_prefer_eac3": True,
    "smart_require_eac3": False,
    "smart_prefer_hdr": True,
    "smart_prefer_webdl": True,
    "smart_prefer_multi": True,
    "smart_exclude_ad": True,
    "smart_max_movie_size_gb": 25,
    "smart_max_series_size_gb": 50,
    "smart_max_results": 5,
    "smart_fallback": True,
    "smart_show_original_release": False,
}


def _config(config: dict[str, Any], key: str) -> Any:
    return config.get(key, DEFAULTS[key])


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _size_gb(torrent: dict[str, Any]) -> float | None:
    size = torrent.get("size")
    if isinstance(size, (int, float)) and size > 0:
        return float(size) / (1024 ** 3)
    return None


def parse_release(torrent: dict[str, Any]) -> ParsedRelease:
    name = str(torrent.get("name") or "")
    text = name.upper()

    if _has(r"\b(?:2160P|4K|UHD)\b", text):
        resolution = "4K"
    elif _has(r"\b1080[PI]?\b", text):
        resolution = "1080p"
    elif _has(r"\b720[PI]?\b", text):
        resolution = "720p"
    else:
        resolution = None

    if _has(r"\b(?:WEB[ ._-]?DL|WEBDL)\b", text):
        source = "WEB-DL"
    elif _has(r"\b(?:WEB[ ._-]?RIP|WEBRIP)\b", text):
        source = "WEBRip"
    elif _has(r"\bREMUX\b", text):
        source = "REMUX"
    elif _has(r"\b(?:BD[ ._-]?RIP|BDRIP)\b", text):
        source = "BDRip"
    elif _has(r"\b(?:BLU[ ._-]?RAY|BLURAY)\b", text):
        source = "BluRay"
    elif _has(r"\bHDTV\b", text):
        source = "HDTV"
    elif _has(r"\b(?:DVD[ ._-]?RIP|DVDRIP)\b", text):
        source = "DVDRip"
    else:
        source = None

    if _has(r"\bAV1\b", text):
        codec = "AV1"
    elif _has(r"\b(?:X265|H[ ._-]?265|HEVC)\b", text):
        codec = "x265"
    elif _has(r"\b(?:X264|H[ ._-]?264|AVC)\b", text):
        codec = "x264"
    else:
        codec = None

    if _has(r"\b(?:TRUE[ ._-]?HD|TRUEHD)\b", text):
        audio = "TrueHD"
    elif _has(r"\b(?:E[ ._-]?AC[ ._-]?3|EAC3|DDP|DD\+|DOLBY DIGITAL PLUS)\b", text):
        audio = "EAC3"
    elif _has(r"\bDTS(?:[ ._-]?(?:HD|X|MA))?\b", text):
        audio = "DTS"
    elif _has(r"\b(?:AC[ ._-]?3|DOLBY DIGITAL)\b", text):
        audio = "AC3"
    elif _has(r"\bAAC(?:[ ._-]?(?:LC|HE))?\b", text):
        audio = "AAC"
    else:
        audio = None

    channel_match = re.search(r"\b(7\.1(?:\.4)?|5\.1(?:\.2|\.4)?|2\.0|2\.1|1\.0)\b", text)
    channels = channel_match.group(1) if channel_match else None

    dolby_vision = _has(r"\b(?:DOLBY[ ._-]?VISION|DOVI|DV)\b", text)
    hdr = dolby_vision or _has(r"\bHDR(?:10\+?)?\b", text)

    vfi = _has(r"\bVFI\b", text)
    vff = _has(r"\bVFF\b", text)
    vostfr = _has(r"\bVOSTFR\b", text)
    vf = vfi or vff or _has(r"\bVF\b", text)
    multi = _has(r"\bMULTI\b", text)

    audio_description = (
        _has(r"(?:^|[ ._|_-])AD(?:$|[ ._|_-])", text)
        or _has(r"\bAUDIO[ ._-]?DESCRIPTION\b", text)
    )

    return ParsedRelease(
        resolution=resolution,
        source=source,
        codec=codec,
        audio=audio,
        channels=channels,
        hdr=hdr,
        dolby_vision=dolby_vision,
        atmos=_has(r"\bATMOS\b", text),
        multi=multi,
        vf=vf,
        vfi=vfi,
        vff=vff,
        vostfr=vostfr,
        audio_description=audio_description,
        size_gb=_size_gb(torrent),
    )


def _passes_hard_filters(parsed: ParsedRelease, stream_type: str, config: dict[str, Any]) -> bool:
    quality_mode = str(_config(config, "smart_quality_mode"))

    if quality_mode == "4k-only" and parsed.resolution != "4K":
        return False
    if bool(_config(config, "smart_require_x265")) and parsed.codec != "x265":
        return False
    if bool(_config(config, "smart_require_eac3")) and parsed.audio != "EAC3":
        return False
    if bool(_config(config, "smart_exclude_ad")) and parsed.audio_description:
        return False

    key = "smart_max_series_size_gb" if stream_type == "series" else "smart_max_movie_size_gb"
    max_size = float(_config(config, key))
    if max_size > 0 and parsed.size_gb is not None and parsed.size_gb > max_size:
        return False

    return True


def _score(parsed: ParsedRelease, config: dict[str, Any]) -> float:
    score = 0.0
    quality_mode = str(_config(config, "smart_quality_mode"))

    if quality_mode == "prefer-4k":
        score += {"4K": 120, "1080p": 70, "720p": 25}.get(parsed.resolution, 0)
    elif quality_mode == "prefer-1080p":
        score += {"1080p": 120, "4K": 90, "720p": 40}.get(parsed.resolution, 0)
    else:
        score += {"4K": 45, "1080p": 35, "720p": 15}.get(parsed.resolution, 0)

    if parsed.codec == "AV1":
        score += 60
    elif parsed.codec == "x265":
        score += 55 if bool(_config(config, "smart_prefer_x265")) else 25
    elif parsed.codec == "x264":
        score += 8

    source_scores = {
        "REMUX": 45,
        "WEB-DL": 42 if bool(_config(config, "smart_prefer_webdl")) else 28,
        "BluRay": 38,
        "BDRip": 32,
        "WEBRip": 20,
        "HDTV": 8,
        "DVDRip": 3,
    }
    score += source_scores.get(parsed.source, 0)

    if parsed.audio == "TrueHD":
        score += 50
    elif parsed.audio == "EAC3":
        score += 45 if bool(_config(config, "smart_prefer_eac3")) else 22
    elif parsed.audio == "DTS":
        score += 32
    elif parsed.audio == "AC3":
        score += 22
    elif parsed.audio == "AAC":
        score += 10

    if parsed.atmos:
        score += 25

    if parsed.channels and parsed.channels.startswith("7.1"):
        score += 12
    elif parsed.channels and parsed.channels.startswith("5.1"):
        score += 8

    if parsed.dolby_vision:
        score += 38 if bool(_config(config, "smart_prefer_hdr")) else 18
    elif parsed.hdr:
        score += 28 if bool(_config(config, "smart_prefer_hdr")) else 12

    if parsed.multi:
        score += 18 if bool(_config(config, "smart_prefer_multi")) else 8

    if parsed.vfi:
        score += 12
    elif parsed.vff:
        score += 10
    elif parsed.vf:
        score += 7

    if parsed.vostfr:
        score += 3

    if parsed.audio_description:
        score -= 120

    if parsed.size_gb is not None:
        score += max(0, 18 - parsed.size_gb * 0.35)

    return score


def rank_stream_candidates(
    items: list[tuple[dict[str, Any], str]],
    stream_type: str,
    config: dict[str, Any],
) -> list[tuple[dict[str, Any], str]]:
    if not items:
        return items

    parsed_items = [(torrent, info_hash, parse_release(torrent)) for torrent, info_hash in items]
    filtered = [item for item in parsed_items if _passes_hard_filters(item[2], stream_type, config)]

    if not filtered and bool(_config(config, "smart_fallback")):
        filtered = [
            item for item in parsed_items
            if not (bool(_config(config, "smart_exclude_ad")) and item[2].audio_description)
        ] or parsed_items

    filtered.sort(
        key=lambda item: (
            -_score(item[2], config),
            item[2].size_gb if item[2].size_gb is not None else float("inf"),
        )
    )

    max_results = max(1, int(_config(config, "smart_max_results")))
    return [(torrent, info_hash) for torrent, info_hash, _ in filtered[:max_results]]


def ranking_label(index: int) -> str:
    if index == 0:
        return "⭐ Meilleur choix"
    if index == 1:
        return "🥈 Choix 2"
    if index == 2:
        return "🥉 Choix 3"
    return f"Choix {index + 1}"


def _format_size(size_gb: float | None) -> str | None:
    if size_gb is None:
        return None
    return f"{size_gb:.1f} Go" if size_gb >= 1 else f"{size_gb:.2f} Go"


def build_compact_title(
    torrent: dict[str, Any],
    source_label: str = "",
    config: dict[str, Any] | None = None,
) -> str:
    config = config or {}
    parsed = parse_release(torrent)
    parts: list[str] = []

    values = [
        parsed.resolution,
        parsed.source,
        parsed.codec,
        "Dolby Vision" if parsed.dolby_vision else ("HDR" if parsed.hdr else None),
        "Atmos" if parsed.atmos else None,
        parsed.audio,
        parsed.channels,
    ]

    if parsed.multi:
        values.append("MULTI")
    elif parsed.vfi:
        values.append("VFI")
    elif parsed.vff:
        values.append("VFF")
    elif parsed.vf:
        values.append("VF")
    elif parsed.vostfr:
        values.append("VOSTFR")

    values.append(_format_size(parsed.size_gb))

    for value in values:
        if value and value not in parts:
            parts.append(value)

    line = " • ".join(parts) or "Source Frenchio"

    source_label = source_label.strip()
    if source_label:
        line += f"\n{source_label}"

    if bool(_config(config, "smart_show_original_release")):
        original = str(torrent.get("name") or "").strip()
        if original:
            line += f"\n{original}"

    return line
