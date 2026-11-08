"""Where chart PNGs are written. File names are built by the server, never the model.

Names follow {tool}_{TICKERS}_{start}_{end}_{yyyymmddHHMMSS}.png with tickers reduced
to [A-Z0-9-]. Every final path is resolved and checked to be inside the data dir.
"""

import os
import platform
import re
import subprocess
from datetime import datetime
from pathlib import Path

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
MAX_TICKER_PART = 60


def data_dir() -> Path:
    """TEARSHEET_DATA_DIR if set, else the repo's data/ folder. Read on every call."""
    return (
        Path(os.environ.get("TEARSHEET_DATA_DIR") or DEFAULT_DATA_DIR)
        .expanduser()
        .resolve()
    )


def sanitize_ticker(ticker: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9-]+", "-", ticker.upper()).strip("-")
    return cleaned or "X"


def chart_filename(
    tool: str, tickers: list[str], start: str | None, end: str | None, now: datetime
) -> str:
    part = "-".join(sanitize_ticker(t) for t in tickers)[:MAX_TICKER_PART]
    dates = [d.replace("-", "") for d in (start, end) if d]
    stamp = now.strftime("%Y%m%d%H%M%S")
    return "_".join([re.sub(r"[^a-z0-9_]+", "", tool), part, *dates, stamp]) + ".png"


def ensure_inside(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"refusing to write outside the data directory: {resolved}")
    return resolved


def save_chart(
    png: bytes,
    tool: str,
    tickers: list[str],
    start: str | None = None,
    end: str | None = None,
    now: datetime | None = None,
) -> Path:
    """Write the PNG under the data dir without overwriting earlier charts."""
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    name = chart_filename(tool, tickers, start, end, now or datetime.now())
    stem, suffix = name.removesuffix(".png"), ".png"
    for n in range(1, 1000):
        candidate = ensure_inside(
            root / (name if n == 1 else f"{stem}_{n}{suffix}"), root
        )
        try:
            with open(candidate, "xb") as f:  # exclusive create: never overwrite
                f.write(png)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("could not find a free chart file name")


def maybe_open(path: Path) -> bool:
    """Open the chart in the system viewer only when TEARSHEET_OPEN_CHARTS=1."""
    if os.environ.get("TEARSHEET_OPEN_CHARTS") != "1":
        return False
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", str(path)])
    elif system == "Linux":
        subprocess.Popen(["xdg-open", str(path)])
    elif system == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    return True
