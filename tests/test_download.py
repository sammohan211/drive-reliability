import io
import zipfile

import httpx
import pytest

from drive_reliability.download import (
    archive_name,
    archive_range,
    download,
    parse_quarter,
    quarter_range,
)

NAME = "data_Q1_2024.zip"


def make_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("2024-01-01.csv", "date,serial_number,failure\n" * 1000)
    return buf.getvalue()


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_archive_name_quarterly():
    assert archive_name(2024, 1) == "data_Q1_2024.zip"


def test_archive_name_yearly_before_2016():
    assert archive_name(2015, 3) == "data_2015.zip"


@pytest.mark.parametrize("year, quarter", [(2024, 0), (2024, 5), (2012, 1)])
def test_archive_name_rejects_invalid(year, quarter):
    with pytest.raises(ValueError):
        archive_name(year, quarter)


def test_archive_range_lists_yearly_archives_once():
    assert archive_range("2014Q3", "2016Q2") == [
        "data_2014.zip",
        "data_2015.zip",
        "data_Q1_2016.zip",
        "data_Q2_2016.zip",
    ]


def test_archive_range_full_history():
    names = archive_range("2013Q2", "2026Q2")
    assert len(names) == 45
    assert names[0] == "data_2013.zip" and names[-1] == "data_Q2_2026.zip"


@pytest.mark.parametrize("text", ["2024Q1", "2024-q1", " 2024Q1 "])
def test_parse_quarter(text):
    assert parse_quarter(text) == (2024, 1)


def test_quarter_range_crosses_year():
    assert quarter_range("2024Q3", "2025Q2") == [(2024, 3), (2024, 4), (2025, 1), (2025, 2)]


def test_quarter_range_rejects_reversed():
    with pytest.raises(ValueError):
        quarter_range("2025Q1", "2024Q4")


def test_download_writes_verified_zip(tmp_path):
    data = make_zip()
    client = mock_client(lambda req: httpx.Response(200, content=data))
    dest = download(NAME, tmp_path, client)
    assert dest.read_bytes() == data
    assert not (tmp_path / "data_Q1_2024.part").exists()


def test_download_skips_existing(tmp_path):
    (tmp_path / NAME).write_bytes(b"already here")

    def handler(req):
        raise AssertionError("should not request an existing archive")

    assert download(NAME, tmp_path, mock_client(handler)).read_bytes() == b"already here"


def test_download_resumes_partial_file(tmp_path):
    data = make_zip()
    split = len(data) // 3
    (tmp_path / "data_Q1_2024.part").write_bytes(data[:split])

    def handler(req):
        assert req.headers["Range"] == f"bytes={split}-"
        return httpx.Response(
            206,
            content=data[split:],
            headers={"Content-Range": f"bytes {split}-{len(data) - 1}/{len(data)}"},
        )

    assert download(NAME, tmp_path, mock_client(handler)).read_bytes() == data


def test_download_restarts_when_range_ignored(tmp_path):
    data = make_zip()
    (tmp_path / "data_Q1_2024.part").write_bytes(b"stale bytes")
    client = mock_client(lambda req: httpx.Response(200, content=data))
    assert download(NAME, tmp_path, client).read_bytes() == data


def test_download_retries_server_errors(tmp_path):
    data = make_zip()
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, content=data)

    download(NAME, tmp_path, mock_client(handler), retry_delay=0)
    assert len(calls) == 3


def test_download_does_not_retry_not_found(tmp_path):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(404)

    with pytest.raises(httpx.HTTPStatusError):
        download(NAME, tmp_path, mock_client(handler), retry_delay=0)
    assert len(calls) == 1
    assert not (tmp_path / NAME).exists()


def test_download_rejects_truncated_file(tmp_path):
    data = make_zip()
    (tmp_path / "data_Q1_2024.part").write_bytes(data[:10])

    def handler(req):  # claims a larger total than it ever sends
        return httpx.Response(
            206, content=data[10:20], headers={"Content-Range": f"bytes 10-19/{len(data)}"}
        )

    with pytest.raises(httpx.TransportError, match="incomplete"):
        download(NAME, tmp_path, mock_client(handler), retries=2, retry_delay=0)
    assert not (tmp_path / NAME).exists()


def test_download_deletes_corrupt_zip(tmp_path):
    client = mock_client(lambda req: httpx.Response(200, content=b"not a zip file"))
    with pytest.raises(ValueError, match="not a valid zip"):
        download(NAME, tmp_path, client)
    assert not (tmp_path / NAME).exists()
    assert not (tmp_path / "data_Q1_2024.part").exists()


def test_download_detects_crc_mismatch(tmp_path):
    data = bytearray(make_zip())
    i = data.index(b"date,serial")  # stored uncompressed, so flip a content byte
    data[i] ^= 0xFF
    client = mock_client(lambda req: httpx.Response(200, content=bytes(data)))
    with pytest.raises(ValueError, match="CRC mismatch"):
        download(NAME, tmp_path, client)
    assert not (tmp_path / NAME).exists()
