"""Backup copies are checksummed, and a bad copy is not restored."""

import json
from pathlib import Path

from ops.backup import create_backup, restore_backup, verify_backup


def test_backup_round_trip_and_a_corrupt_copy_is_refused(tmp_path):
    source = tmp_path / "desk-users"
    source.mkdir()
    (source / "ada.json").write_text(json.dumps({"id": "ada", "capital": 1000}), encoding="utf-8")
    nested = source / "paper"
    nested.mkdir()
    (nested / "ada.json").write_text("[]", encoding="utf-8")
    backup = tmp_path / "backup"
    created = create_backup(source, backup)
    assert created["ok"] is True
    assert created["files"] == 2
    assert verify_backup(backup)["ok"] is True
    restored = tmp_path / "restored"
    assert restore_backup(backup, restored)["ok"] is True
    assert json.loads((restored / "ada.json").read_text(encoding="utf-8"))["capital"] == 1000
    assert (source / "ada.json").read_text(encoding="utf-8") == (restored / "ada.json").read_text(encoding="utf-8")
    target = backup / "files" / "ada.json"
    target.write_text("tampered", encoding="utf-8")
    assert verify_backup(backup)["reason"] == "checksum_mismatch"
    refused = restore_backup(backup, tmp_path / "should-stay-empty")
    assert refused["ok"] is False
    assert not (tmp_path / "should-stay-empty").exists()


def test_restore_refuses_a_destination_that_already_has_files(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "one.txt").write_text("ok", encoding="utf-8")
    backup = tmp_path / "bak"
    assert create_backup(source, backup)["ok"] is True
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("keep", encoding="utf-8")
    assert restore_backup(backup, occupied)["reason"] == "destination_not_empty"
    assert (occupied / "keep.txt").read_text(encoding="utf-8") == "keep"
