import json
import os
from pathlib import Path
from unittest import mock

import pytest

from cognits.storage.files import write_file_atomic


def test_write_atomic_creates_file(tmp_path: Path):
    path = tmp_path / "target.json"
    data = b'{"hello": "world"}'
    write_file_atomic(path, data)
    assert path.read_bytes() == data


def test_write_atomic_overwrites(tmp_path: Path):
    path = tmp_path / "target.json"
    path.write_text("old")
    write_file_atomic(path, b"new")
    assert path.read_text() == "new"


def test_write_atomic_no_truncation_on_crash(tmp_path: Path):
    path = tmp_path / "target.json"
    path.write_text("original")

    original_write = os.write

    def failing_write(fd, data):
        raise OSError("simulated crash mid-write")

    with mock.patch("os.write", side_effect=failing_write):
        with pytest.raises(OSError):
            write_file_atomic(path, b"replaced")

    assert path.read_text() == "original"

    tmp_files = list(tmp_path.glob("*.tmp"))
    assert not tmp_files


def test_write_atomic_cleans_temp_on_base_exception(tmp_path: Path):
    path = tmp_path / "target.json"

    original_write = os.write

    def failing_write(fd, data):
        raise BaseException("simulated crash")

    with mock.patch("os.write", side_effect=failing_write):
        with pytest.raises(BaseException):
            write_file_atomic(path, b"data")

    assert not path.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_write_atomic_fsyncs_temp_file(tmp_path: Path):
    path = tmp_path / "target.json"

    with mock.patch("os.fsync") as mock_fsync:
        write_file_atomic(path, b"data")

    temp_fsync = any(
        call_args[0][0] != os.open(str(path.parent), os.O_RDONLY)
        for call_args in mock_fsync.call_args_list
    )
    assert temp_fsync, "temp file fsync was not called"


def test_write_atomic_fsyncs_directory(tmp_path: Path):
    path = tmp_path / "target.json"

    with mock.patch("os.fsync") as mock_fsync:
        write_file_atomic(path, b"data")

    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    dir_fsync = any(
        call_args[0][0] == dir_fd
        for call_args in mock_fsync.call_args_list
    )
    os.close(dir_fd)
    assert dir_fsync, "directory fsync was not called"


def test_write_atomic_temp_in_same_directory(tmp_path: Path):
    path = tmp_path / "target.json"

    with mock.patch("os.replace") as mock_replace:
        write_file_atomic(path, b"data")

    mock_replace.assert_called_once()
    src, dst = mock_replace.call_args[0]
    assert src.parent == dst.parent


def test_save_session_uses_write_atomic(tmp_path: Path):
    from cognits.storage.files import Session, Store

    store = Store(tmp_path)
    session = Session(id="test-id", name="Test")

    with mock.patch(
        "cognits.storage.files.write_file_atomic"
    ) as mock_write:
        store.save_session(session)

    mock_write.assert_called_once()
    args_path, args_data = mock_write.call_args[0]
    assert args_path.name == "test-id.json"
    parsed = json.loads(args_data)
    assert parsed["id"] == "test-id"


def test_reorder_sessions_uses_write_atomic(tmp_path: Path):
    from cognits.storage.files import Store

    store = Store(tmp_path)

    with mock.patch(
        "cognits.storage.files.write_file_atomic"
    ) as mock_write:
        store.reorder_sessions(["a", "b", "c"])

    mock_write.assert_called_once()
    args_path, args_data = mock_write.call_args[0]
    assert args_path.name == "session_order.json"
    parsed = json.loads(args_data)
    assert parsed == ["a", "b", "c"]
