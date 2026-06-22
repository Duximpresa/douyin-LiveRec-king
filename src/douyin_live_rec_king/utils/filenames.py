"""Safe recording filename construction for Windows."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_component(value: str, fallback: str = "unknown") -> str:
    cleaned = _INVALID.sub("_", value).strip(" .")
    return cleaned[:80] or fallback


def recording_path(
    output_dir: Path,
    platform: str,
    anchor_name: str,
    extension: str,
    template: str = "{platform}_{anchor}_{time}",
    title: str = "",
    folder_by_platform: bool = False,
    folder_by_anchor: bool = False,
    segmented: bool = False,
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if folder_by_platform:
        output_dir /= safe_component(platform)
    if folder_by_anchor:
        output_dir /= safe_component(anchor_name)
    values = {
        "platform": safe_component(platform),
        "anchor": safe_component(anchor_name),
        "title": safe_component(title, ""),
        "time": timestamp,
    }
    try:
        stem = template.format(**values)
    except (KeyError, ValueError):
        stem = "{platform}_{anchor}_{time}".format(**values)
    stem = safe_component(stem)
    if segmented:
        stem += "_%03d"
    filename = f"{stem}.{extension.lstrip('.')}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / filename
