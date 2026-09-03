"""RadioTAK console package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("radiotak")
except PackageNotFoundError:
    from pathlib import Path

    _v = Path(__file__).resolve().parents[1] / "VERSION"
    __version__ = _v.read_text(encoding="utf-8").strip() if _v.exists() else "0.0.0"
