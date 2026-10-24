import zipfile

import duckdb
import pytest

from drive_reliability.convert import convert, extract_csvs

HEADER = "date,serial_number,model,capacity_bytes,failure,smart_9_normalized,smart_9_raw"
DAY1 = f"{HEADER}\n2024-01-01,S1,ST4000DM000,4000787030016,0,98,15736\n"
# A later day gains a column, as Backblaze's files do over time
DAY2 = (
    f"{HEADER},datacenter\n"
    "2024-01-02,S1,ST4000DM000,4000787030016,1,,15760,phx1\n"
    "2024-01-02,S2,HGST HMS5C4040ALE640,4000787030016,0,100,9000,sac2\n"
)


def make_archive(path, files):
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return path


@pytest.fixture
def archive(tmp_path):
    return make_archive(
        tmp_path / "data_Q1_2024.zip",
        {
            "data_Q1_2024/2024-01-01.csv": DAY1,
            "data_Q1_2024/2024-01-02.csv": DAY2,
            "__MACOSX/data_Q1_2024/._2024-01-01.csv": "junk",
            "data_Q1_2024/.DS_Store": "junk",
        },
    )


def run(archive, tmp_path):
    return convert(archive, tmp_path / "parquet", tmp_path / "tmp")


def test_extract_skips_macos_junk_and_flattens(archive, tmp_path):
    paths = extract_csvs(archive, tmp_path / "out")
    assert [p.name for p in paths] == ["2024-01-01.csv", "2024-01-02.csv"]
    assert all(p.parent == tmp_path / "out" for p in paths)


def test_extract_never_writes_outside_dest(tmp_path):
    bad = make_archive(tmp_path / "bad.zip", {"../../escape.csv": DAY1})
    (path,) = extract_csvs(bad, tmp_path / "out")
    assert path == tmp_path / "out" / "escape.csv"


def test_extract_rejects_archive_without_csvs(tmp_path):
    empty = make_archive(tmp_path / "empty.zip", {"readme.txt": "hi"})
    with pytest.raises(ValueError, match="no CSV"):
        extract_csvs(empty, tmp_path / "out")


def test_convert_writes_all_rows_with_types(archive, tmp_path):
    dest = run(archive, tmp_path)
    con = duckdb.connect()
    types = dict(
        con.execute(f"SELECT column_name, column_type FROM (DESCRIBE '{dest}')").fetchall()
    )
    assert types == {
        "date": "DATE",
        "serial_number": "VARCHAR",
        "model": "VARCHAR",
        "capacity_bytes": "BIGINT",
        "failure": "TINYINT",
        "smart_9_normalized": "DOUBLE",
        "smart_9_raw": "DOUBLE",
        "datacenter": "VARCHAR",
    }
    rows = con.execute(
        f"SELECT serial_number, failure, smart_9_normalized, datacenter FROM '{dest}'"
        " ORDER BY date, serial_number"
    ).fetchall()
    assert rows == [("S1", 0, 98.0, None), ("S1", 1, None, "phx1"), ("S2", 0, 100.0, "sac2")]


def test_convert_cleans_up_temp_files(archive, tmp_path):
    run(archive, tmp_path)
    assert not (tmp_path / "tmp" / "data_Q1_2024").exists()
    assert not list((tmp_path / "parquet").glob("*.part"))
    assert archive.exists()  # the zip is kept


def test_convert_skips_existing(archive, tmp_path):
    out = tmp_path / "parquet" / "data_Q1_2024.parquet"
    out.parent.mkdir()
    out.write_bytes(b"already here")
    assert run(archive, tmp_path).read_bytes() == b"already here"


def test_convert_fails_loudly_on_bad_value(tmp_path):
    bad = make_archive(
        tmp_path / "data_Q1_2024.zip",
        {"2024-01-01.csv": f"{HEADER}\n2024-01-01,S1,M,4000787030016,0,98,not-a-number\n"},
    )
    with pytest.raises(duckdb.ConversionException):
        run(bad, tmp_path)
    assert not list((tmp_path / "parquet").iterdir())
    assert not (tmp_path / "tmp" / "data_Q1_2024").exists()


def test_convert_rejects_missing_columns(tmp_path):
    bad = make_archive(
        tmp_path / "data_Q1_2024.zip", {"2024-01-01.csv": "date,model\n2024-01-01,M\n"}
    )
    with pytest.raises(ValueError, match="missing expected columns"):
        run(bad, tmp_path)
