"""Audit the Parquet files in data/parquet/ for column drift across archives.

Backblaze added SMART columns and fields like `datacenter` over the years. Each
Parquet file keeps its own columns and DuckDB aligns them by name, so this checks
that the names and types line up and that a column added later reads back as
NULL in the archives that predate it.
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

from drive_reliability.convert import PARQUET_DIR

ARCHIVE_RE = re.compile(r"data_(?:Q(\d)_)?(\d{4})")


def archive_order(path: Path) -> tuple[int, int]:
    """Sort key (year, quarter) for an archive file. Yearly archives sort as quarter 0."""
    m = ARCHIVE_RE.fullmatch(path.stem)
    if not m:
        raise ValueError(f"not an archive name: {path.name}")
    quarter, year = m.groups()
    return int(year), int(quarter or 0)


def read_schemas(paths: list[Path]) -> dict[str, dict[str, str]]:
    """Map each archive stem to its {column: DuckDB type}, in chronological order.

    Reads only the Parquet footers, not the data.
    """
    con = duckdb.connect()
    try:
        return {
            p.stem: dict(
                con.execute(
                    f"SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM '{p}')"
                ).fetchall()
            )
            for p in sorted(paths, key=archive_order)
        }
    finally:
        con.close()


def column_spans(schemas: dict[str, dict[str, str]]) -> dict[str, dict]:
    """For each column: first and last archive that has it, and archives missing in between."""
    archives = list(schemas)
    spans = {}
    for col in {c for cols in schemas.values() for c in cols}:
        present = [i for i, a in enumerate(archives) if col in schemas[a]]
        first, last = present[0], present[-1]
        spans[col] = {
            "first": archives[first],
            "last": archives[last],
            "gaps": [a for a in archives[first : last + 1] if col not in schemas[a]],
        }
    return spans


def near_duplicates(columns: set[str]) -> list[list[str]]:
    """Groups of column names that differ only in case, spaces, underscores or dashes."""
    groups = defaultdict(list)
    for col in columns:
        groups[re.sub(r"[\s_\-]", "", col.lower())].append(col)
    return sorted(sorted(g) for g in groups.values() if len(g) > 1)


def type_conflicts(schemas: dict[str, dict[str, str]]) -> dict[str, dict[str, list[str]]]:
    """Columns stored with more than one type: {column: {type: [archives]}}."""
    types = defaultdict(lambda: defaultdict(list))
    for archive, cols in schemas.items():
        for col, typ in cols.items():
            types[col][typ].append(archive)
    return {col: dict(t) for col, t in sorted(types.items()) if len(t) > 1}


def null_fill_counts(paths: list[Path], column: str) -> dict[str, int]:
    """Non-NULL count of column per archive, reading all files together by name.

    Archives that predate the column should come back as 0, not as an error or as
    values from a misaligned column. Scans the column's data, so pass few columns.
    """
    con = duckdb.connect()
    try:
        rows = con.execute(
            f'SELECT filename, count("{column}") FROM read_parquet(?, union_by_name = true,'
            " filename = true) GROUP BY filename",
            [[str(p) for p in paths]],
        ).fetchall()
    finally:
        con.close()
    return {Path(f).stem: n for f, n in rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet-dir", type=Path, default=PARQUET_DIR)
    parser.add_argument(
        "--null-check",
        nargs="*",
        help="columns to scan for NULL fill (default: datacenter and the newest SMART column)",
    )
    args = parser.parse_args()
    paths = sorted(args.parquet_dir.glob("*.parquet"), key=archive_order)
    if not paths:
        sys.exit(f"no Parquet files in {args.parquet_dir}")

    schemas = read_schemas(paths)
    archives = list(schemas)
    spans = column_spans(schemas)
    problems = []
    print(f"{len(schemas)} archives, {len(spans)} distinct columns")

    print("\nColumns by first archive:")
    by_first = defaultdict(list)
    for col, s in spans.items():
        by_first[s["first"]].append(col)
    for archive in archives:
        if by_first[archive]:
            print(f"  {archive}: {len(by_first[archive])}  {', '.join(sorted(by_first[archive]))}")

    latest = archives[-1]
    dropped = {c: s["last"] for c, s in spans.items() if s["last"] != latest}
    if dropped:
        print("\nColumns no longer present (last archive):")
        for col, last in sorted(dropped.items()):
            print(f"  {col}: {last}")

    gaps = {c: s["gaps"] for c, s in spans.items() if s["gaps"]}
    for col, missing in sorted(gaps.items()):
        problems.append(f"{col} missing between first and last appearance: {', '.join(missing)}")
    for group in near_duplicates(set(spans)):
        problems.append(f"near-duplicate names: {', '.join(group)}")
    for col, types in type_conflicts(schemas).items():
        problems.append(f"{col} has types {', '.join(f'{t} ({len(a)})' for t, a in types.items())}")

    checks = args.null_check
    if checks is None:
        smart = [c for c in spans if c.startswith("smart_")]
        newest = max(smart, key=lambda c: (archives.index(spans[c]["first"]), c), default=None)
        checks = [c for c in ["datacenter", newest] if c in spans]
    for col in checks:
        if col not in spans:
            problems.append(f"{col}: not in any archive")
            continue
        counts = null_fill_counts(paths, col)
        before = archives[: archives.index(spans[col]["first"])]
        leaked = {a: counts[a] for a in before if counts[a]}
        print(f"\nNULL fill for {col} (first in {spans[col]['first']}):")
        print(f"  {len(before)} earlier archives, all NULL: {not leaked}")
        print(f"  non-NULL from first appearance on: {sum(counts.values()):,}")
        if leaked:
            problems.append(f"{col} has values before it was added: {leaked}")

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  {p}")
        sys.exit(1)
    print("\nNo problems found")


if __name__ == "__main__":
    main()
