import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from tearsheet.viz import storage

NOW = datetime(2026, 11, 8, 9, 30, 15)


@pytest.mark.parametrize(
    "ticker",
    [
        "../../etc/passwd",
        "..\\..\\x",
        "/abs/path",
        "A/B",
        "^GSPC",
        "EURUSD=X",
        "~root",
        "..",
    ],
)
def test_crafted_ticker_cannot_escape_data_dir(chart_dir, ticker):
    path = storage.save_chart(
        b"png", "price_chart", [ticker], "2024-01-01", "2024-12-31", NOW
    )
    assert path.parent == chart_dir.resolve()
    assert path.resolve().is_relative_to(chart_dir.resolve())
    assert set(path.name) <= set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    )
    assert ".." not in path.name.removesuffix(".png")


def test_filename_format():
    name = storage.chart_filename(
        "comparison", ["NVDA", "brk.b"], "2024-01-02", "2024-12-31", NOW
    )
    assert name == "comparison_NVDA-BRK-B_20240102_20241231_20261108093015.png"


def test_ensure_inside_rejects_outside(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    with pytest.raises(ValueError):
        storage.ensure_inside(root / ".." / "evil.png", root)
    assert storage.ensure_inside(root / "ok.png", root) == (root / "ok.png").resolve()


def test_same_second_does_not_overwrite(chart_dir):
    a = storage.save_chart(
        b"first", "price_chart", ["AAPL"], "2024-01-01", "2024-02-01", NOW
    )
    b = storage.save_chart(
        b"second", "price_chart", ["AAPL"], "2024-01-01", "2024-02-01", NOW
    )
    assert a != b and a.read_bytes() == b"first" and b.read_bytes() == b"second"


def test_data_dir_env_and_default(monkeypatch, tmp_path):
    monkeypatch.setenv("TEARSHEET_DATA_DIR", str(tmp_path / "x"))
    assert storage.data_dir() == (tmp_path / "x").resolve()
    monkeypatch.delenv("TEARSHEET_DATA_DIR")
    assert storage.data_dir() == storage.DEFAULT_DATA_DIR
    assert storage.DEFAULT_DATA_DIR.name == "data"


def test_viewer_only_opens_when_enabled(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(storage.platform, "system", lambda: "Darwin")
    assert storage.maybe_open(Path(tmp_path / "c.png")) is False and calls == []
    monkeypatch.setenv("TEARSHEET_OPEN_CHARTS", "1")
    assert storage.maybe_open(Path(tmp_path / "c.png")) is True and len(calls) == 1
