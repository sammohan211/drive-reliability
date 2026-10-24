"""Download Backblaze quarterly drive-stats archives into data/raw/."""

import argparse
import re
from pathlib import Path

import httpx

BASE_URL = "https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data"
RAW_DIR = Path("data/raw")


def quarter_url(year: int, quarter: int) -> str:
    """URL of one quarterly archive (Backblaze publishes quarterly zips from 2016)."""
    if not 1 <= quarter <= 4:
        raise ValueError(f"quarter must be 1-4, got {quarter}")
    if year < 2016:
        raise ValueError("pre-2016 data is published as yearly archives; not supported")
    return f"{BASE_URL}/data_Q{quarter}_{year}.zip"


def parse_quarter(text: str) -> tuple[int, int]:
    """Parse '2024Q1' (or '2024-Q1') into (2024, 1)."""
    match = re.fullmatch(r"(\d{4})-?Q([1-4])", text.strip().upper())
    if not match:
        raise ValueError(f"expected a quarter like 2024Q1, got {text!r}")
    return int(match.group(1)), int(match.group(2))


def quarter_range(start: str, end: str) -> list[tuple[int, int]]:
    """All quarters from start to end inclusive."""
    (y, q), stop = parse_quarter(start), parse_quarter(end)
    if (y, q) > stop:
        raise ValueError(f"start {start} is after end {end}")
    quarters = []
    while (y, q) <= stop:
        quarters.append((y, q))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return quarters


def download(year: int, quarter: int, out_dir: Path = RAW_DIR) -> Path:
    """Stream one archive to disk. Skips files that already exist."""
    url = quarter_url(year, quarter)
    dest = out_dir / url.rsplit("/", 1)[1]
    if dest.exists():
        print(f"skip  {dest.name} (exists)")
        return dest
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in resp.iter_bytes(chunk_size=1 << 20):
                f.write(chunk)
    tmp.rename(dest)
    print(f"done  {dest.name}")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start", help="first quarter, e.g. 2023Q1")
    parser.add_argument("end", help="last quarter, e.g. 2026Q2")
    parser.add_argument("--out-dir", type=Path, default=RAW_DIR)
    args = parser.parse_args()
    for year, quarter in quarter_range(args.start, args.end):
        download(year, quarter, args.out_dir)


if __name__ == "__main__":
    main()
