import pytest

from startup_assistant import storage
from startup_assistant.storage import atomic_write_text


def test_writes_content(tmp_path):
    path = tmp_path / "data.json"
    atomic_write_text(path, "hello café ✓")
    assert path.read_text(encoding="utf-8") == "hello café ✓"


def test_creates_missing_parent_dirs(tmp_path):
    path = tmp_path / "a" / "b" / "data.json"
    atomic_write_text(path, "x")
    assert path.read_text(encoding="utf-8") == "x"


def test_overwrites_existing_content(tmp_path):
    path = tmp_path / "data.json"
    path.write_text("old", encoding="utf-8")
    atomic_write_text(path, "new")
    assert path.read_text(encoding="utf-8") == "new"


def test_leaves_no_stray_temp_files(tmp_path):
    path = tmp_path / "data.json"
    atomic_write_text(path, "one")
    atomic_write_text(path, "two")
    assert [p.name for p in tmp_path.iterdir()] == ["data.json"]


def test_failure_removes_temp_file_and_keeps_original(tmp_path, monkeypatch):
    path = tmp_path / "data.json"
    path.write_text("old", encoding="utf-8")

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(storage.os, "replace", boom)
    with pytest.raises(OSError, match="replace failed"):
        atomic_write_text(path, "new")
    assert [p.name for p in tmp_path.iterdir()] == ["data.json"]
    assert path.read_text(encoding="utf-8") == "old"


def test_locked_creates_lock_file_next_to_target(tmp_path):
    target = tmp_path / "sub" / "data.json"
    with storage.locked(target):
        assert (tmp_path / "sub" / "data.json.lock").exists()


def test_locked_is_exclusive(tmp_path, monkeypatch):
    import filelock

    monkeypatch.setattr(storage, "LOCK_TIMEOUT_SECONDS", 0.2)
    target = tmp_path / "data.json"
    with storage.locked(target):
        with pytest.raises(filelock.Timeout):
            with storage.locked(target):
                pass


def test_locked_none_path_is_a_noop():
    with storage.locked(None):
        pass
