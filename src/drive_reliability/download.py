"""Download Backblaze drive-stats archives into data/raw/.

Backblaze publishes one zip per year for 2013-2015 and one per quarter from 2016.
Downloads resume after interruption, retry on network errors, and are checked
(size and zip CRCs) before being renamed from .part to .zip.
"""

import argparse
import re
import sys
import time
import zipfile
from pathlib import Path

import httpx

BASE_URL = "https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data"
RAW_DIR = Path("data/raw")
FIRST_QUARTERLY_YEAR = 2016
FIRST_YEAR = 2013


def archive_name(year: int, quarter: int) -> str:
    """Name of the archive holding a quarter: yearly before 2016, quarterly after."""
    if not 1 <= quarter <= 4:
        raise ValueError(f"quarter must be 1-4, got {quarter}")
    if year < FIRST_YEAR:
        raise ValueError(f"Backblaze data starts in {FIRST_YEAR}, got {year}")
    if year < FIRST_QUARTERLY_YEAR:
        return f"data_{year}.zip"
    return f"data_Q{quarter}_{year}.zip"


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


def archive_range(start: str, end: str) -> list[str]:
    """Archive names covering start..end, in order; yearly archives appear once."""
    names = [archive_name(y, q) for y, q in quarter_range(start, end)]
    return list(dict.fromkeys(names))


def verify_zip(path: Path) -> None:
    """Raise if the zip is unreadable or any member fails its CRC check."""
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
    except zipfile.BadZipFile as e:
        raise ValueError(f"{path.name}: not a valid zip ({e})") from e
    if bad is not None:
        raise ValueError(f"{path.name}: CRC mismatch in {bad}")


def _fetch(client: httpx.Client, url: str, tmp: Path) -> None:
    """Fetch url into tmp, resuming from tmp's current size. Checks the final size."""
    offset = tmp.stat().st_size if tmp.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with client.stream("GET", url, headers=headers) as resp:
        if resp.status_code == 416:  # .part already holds the whole file
            return
        resp.raise_for_status()
        if resp.status_code == 206:
            total = int(resp.headers["Content-Range"].rsplit("/", 1)[1])
            mode = "ab"
        else:  # server ignored the Range header: start over
            total = int(resp.headers.get("Content-Length", -1))
            mode = "wb"
        with tmp.open(mode) as f:
            for chunk in resp.iter_bytes(chunk_size=1 << 20):
                f.write(chunk)
    size = tmp.stat().st_size
    if total >= 0 and size != total:
        raise httpx.TransportError(f"incomplete: got {size} of {total} bytes")


def download(
    name: str,
    out_dir: Path = RAW_DIR,
    client: httpx.Client | None = None,
    retries: int = 5,
    retry_delay: float = 10.0,
) -> Path:
    """Download one archive, verify it, and return its path. Skips files that exist."""
    dest = out_dir / name
    if dest.exists():
        print(f"skip  {name} (exists)", flush=True)
        return dest
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    url = f"{BASE_URL}/{name}"
    own_client = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=60)
    try:
        for attempt in range(1, retries + 1):
            try:
                _fetch(client, url, tmp)
                break
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                # 4xx (e.g. 404 for an unpublished quarter) won't fix itself; don't retry
                status = getattr(getattr(e, "response", None), "status_code", 500)
                if status < 500 or attempt == retries:
                    raise
                print(f"retry {name} ({attempt}/{retries - 1}): {e}", flush=True)
                time.sleep(retry_delay * attempt)
    finally:
        if own_client:
            client.close()
    try:
        verify_zip(tmp)
    except ValueError:
        tmp.unlink()
        raise
    tmp.rename(dest)
    print(f"done  {name} ({dest.stat().st_size / 1e9:.2f} GB)", flush=True)
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start", help="first quarter, e.g. 2013Q2")
    parser.add_argument("end", help="last quarter, e.g. 2026Q2")
    parser.add_argument("--out-dir", type=Path, default=RAW_DIR)
    args = parser.parse_args()
    failed = []
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for name in archive_range(args.start, args.end):
            try:
                download(name, args.out_dir, client)
            except (httpx.HTTPError, ValueError) as e:
                print(f"FAIL  {name}: {e}", flush=True)
                failed.append(name)
    if failed:
        sys.exit(f"{len(failed)} archive(s) failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
