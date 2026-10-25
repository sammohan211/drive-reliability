import duckdb
import pytest

from drive_reliability.audit import (
    archive_order,
    column_spans,
    near_duplicates,
    null_fill_counts,
    read_schemas,
    type_conflicts,
)


def write_parquet(path, select):
    duckdb.sql(f"COPY (SELECT {select}) TO '{path}' (FORMAT parquet)")
    return path


@pytest.fixture
def fleet(tmp_path):
    # Written out of order. datacenter is added in Q1_2016; smart_1_raw skips Q1_2016 (a gap)
    return [
        write_parquet(
            tmp_path / "data_2015.parquet", "'S1' AS serial_number, 1.0::DOUBLE AS smart_1_raw"
        ),
        write_parquet(
            tmp_path / "data_Q2_2016.parquet",
            "'S1' AS serial_number, 3.0::DOUBLE AS smart_1_raw, 'phx1' AS datacenter",
        ),
        write_parquet(
            tmp_path / "data_Q1_2016.parquet", "'S1' AS serial_number, 'sac2' AS datacenter"
        ),
    ]


def test_archive_order_is_chronological(tmp_path):
    names = ["data_Q1_2017", "data_Q2_2016", "data_2015", "data_Q4_2016", "data_2013"]
    ordered = sorted((tmp_path / f"{n}.parquet" for n in names), key=archive_order)
    assert [p.stem for p in ordered] == [
        "data_2013",
        "data_2015",
        "data_Q2_2016",
        "data_Q4_2016",
        "data_Q1_2017",
    ]


def test_archive_order_rejects_other_names(tmp_path):
    with pytest.raises(ValueError, match="not an archive name"):
        archive_order(tmp_path / "lifecycle.parquet")


def test_read_schemas_in_order_with_types(fleet):
    schemas = read_schemas(fleet)
    assert list(schemas) == ["data_2015", "data_Q1_2016", "data_Q2_2016"]
    assert schemas["data_Q2_2016"] == {
        "serial_number": "VARCHAR",
        "smart_1_raw": "DOUBLE",
        "datacenter": "VARCHAR",
    }


def test_column_spans_finds_first_last_and_gaps(fleet):
    spans = column_spans(read_schemas(fleet))
    assert spans["datacenter"] == {"first": "data_Q1_2016", "last": "data_Q2_2016", "gaps": []}
    assert spans["smart_1_raw"] == {
        "first": "data_2015",
        "last": "data_Q2_2016",
        "gaps": ["data_Q1_2016"],
    }


def test_near_duplicates_groups_spelling_variants():
    cols = {"datacenter", "data_center", "Data Center", "smart_1_raw", "smart_10_raw"}
    assert near_duplicates(cols) == [["Data Center", "data_center", "datacenter"]]


def test_type_conflicts():
    schemas = {
        "data_2015": {"smart_1_raw": "DOUBLE", "model": "VARCHAR"},
        "data_Q1_2016": {"smart_1_raw": "VARCHAR", "model": "VARCHAR"},
    }
    assert type_conflicts(schemas) == {
        "smart_1_raw": {"DOUBLE": ["data_2015"], "VARCHAR": ["data_Q1_2016"]}
    }


def test_null_fill_counts_zero_before_column_exists(fleet):
    assert null_fill_counts(fleet, "datacenter") == {
        "data_2015": 0,
        "data_Q1_2016": 1,
        "data_Q2_2016": 1,
    }
