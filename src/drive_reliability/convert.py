"""Convert downloaded Backblaze archives in data/raw/ to Parquet in data/parquet/.

One archive at a time: extract its daily CSVs to a temporary folder, write one
Parquet file with all columns, then delete the CSVs. The zips are kept.
"""

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

import duckdb

from drive_reliability.download import RAW_DIR

PARQUET_DIR = Path("data/parquet")
TMP_DIR = Path("data/tmp")

# Columns with a fixed type in every archive. smart_* columns become DOUBLE (raw values
# fit exactly up to 2^53); anything else Backblaze added later stays VARCHAR.
FIXED_TYPES = {
    "date": "DATE",
    "serial_number": "VARCHAR",
    "model": "VARCHAR",
    "capacity_bytes": "BIGINT",
    "failure": "TINYINT",
}


def extract_csvs(archive: Path, dest: Path) -> list[Path]:
    """Extract the daily CSVs from archive into dest. Skips macOS metadata and folders."""
    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = Path(info.filename)
            if info.is_dir() or "__MACOSX" in name.parts or name.suffix != ".csv":
                continue
            out = dest / name.name  # flatten: never write outside dest
            with zf.open(info) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1 << 20)
            paths.append(out)
    if not paths:
        raise ValueError(f"{archive.name}: no CSV files found")
    return sorted(paths)


def column_type(name: str) -> str:
    """Return the DuckDB type for a column: from FIXED_TYPES, DOUBLE for smart_*, else VARCHAR."""
    if name in FIXED_TYPES:
        return FIXED_TYPES[name]
    return "DOUBLE" if name.startswith("smart_") else "VARCHAR"


def column_expr(name: str) -> str:
    """SQL casting one text column to its type.

    A few daily files (e.g. 2018-02-25, 2019-06-17) were re-saved in Excel before
    publication: dates became M/D/YY and large numbers E-notation, rounded to 6
    significant digits. Both forms are accepted; DOUBLE columns already parse
    E-notation. Any other unparseable value still fails the plain CAST at the end.
    """
    col, typ = f'"{name}"', column_type(name)
    if typ == "DATE":
        # Match the M/D/YY shape explicitly: a plain CAST reads '12/5/18' as year 12
        expr = (
            f"CASE WHEN regexp_full_match({col}, '\\d{{1,2}}/\\d{{1,2}}/\\d{{2}}')"
            f" THEN CAST(STRPTIME({col}, '%m/%d/%y') AS DATE)"
            f" ELSE CAST({col} AS DATE) END"
        )
    elif typ == "BIGINT":
        expr = (
            f"CASE WHEN {col} ILIKE '%e+%' THEN CAST(CAST({col} AS DOUBLE) AS BIGINT)"
            f" ELSE CAST({col} AS BIGINT) END"
        )
    else:
        expr = f"CAST({col} AS {typ})"
    return f"{expr} AS {col}"


def csvs_to_parquet(
    csvs: list[Path], out: Path, temp_dir: Path = TMP_DIR / "duckdb", memory_limit: str = "6GB"
) -> int:
    """Write the CSVs to one Parquet file, columns aligned by name. Returns the row count.

    CSVs are read as text and cast explicitly, so a value that doesn't fit its type
    fails the conversion instead of being silently turned into NULL.
    """
    con = duckdb.connect()
    try:
        con.execute("SET memory_limit = ?", [memory_limit])
        con.execute("SET temp_directory = ?", [str(temp_dir)])
        raw = con.read_csv(
            [str(p) for p in csvs], header=True, all_varchar=True, union_by_name=True
        )
        missing = set(FIXED_TYPES) - set(raw.columns)
        if missing:
            raise ValueError(f"missing expected columns: {sorted(missing)}")
        select = ", ".join(column_expr(c) for c in raw.columns)
        raw.select(select).write_parquet(str(out), compression="zstd")
        return con.execute("SELECT count(*) FROM read_parquet(?)", [str(out)]).fetchone()[0]
    finally:
        con.close()


def convert(archive: Path, out_dir: Path = PARQUET_DIR, tmp_dir: Path = TMP_DIR) -> Path:
    """Convert one archive to out_dir/<archive stem>.parquet. Skips files that exist."""
    dest = out_dir / f"{archive.stem}.parquet"
    if dest.exists():
        print(f"skip  {dest.name} (exists)", flush=True)
        return dest
    out_dir.mkdir(parents=True, exist_ok=True)
    work = tmp_dir / archive.stem
    part = dest.with_suffix(".parquet.part")
    try:
        csvs = extract_csvs(archive, work)
        rows = csvs_to_parquet(csvs, part, tmp_dir / "duckdb")
        part.rename(dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    size = dest.stat().st_size / 1e9
    print(f"done  {dest.name} ({len(csvs)} days, {rows:,} rows, {size:.2f} GB)", flush=True)
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "archives", nargs="*", type=Path, help="zips to convert (default: all in --raw-dir)"
    )
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--out-dir", type=Path, default=PARQUET_DIR)
    args = parser.parse_args()
    # Only finished .zip files: in-progress downloads are still named .part
    archives = args.archives or sorted(args.raw_dir.glob("*.zip"))
    failed = []
    for archive in archives:
        try:
            convert(archive, args.out_dir)
        except (duckdb.Error, ValueError, zipfile.BadZipFile) as e:
            print(f"FAIL  {archive.name}: {e}", flush=True)
            failed.append(archive.name)
    if failed:
        sys.exit(f"{len(failed)} archive(s) failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
