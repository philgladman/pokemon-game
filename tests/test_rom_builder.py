from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from sameboy import rom_builder


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    checkout = tmp_path / "source"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    (checkout / "input.txt").write_text("canonical source\n")
    subprocess.run(["git", "-C", str(checkout), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    revision = rom_builder.git(checkout, "rev-parse", "HEAD").decode().strip()
    monkeypatch.setattr(rom_builder, "PINNED_REVISION", revision)
    return checkout


def test_export_uses_pinned_tree_not_untracked_or_hidden_worktree_edits(
    source: Path, tmp_path: Path
) -> None:
    (source / "untracked.txt").write_text("not an input")
    subprocess.run(
        ["git", "-C", str(source), "update-index", "--assume-unchanged", "input.txt"],
        check=True,
    )
    (source / "input.txt").write_text("hidden edit")
    exported = tmp_path / "exported"
    exported.mkdir()
    rom_builder.export_source(source, exported)
    assert (exported / "input.txt").read_text() == "canonical source\n"
    assert not (exported / "untracked.txt").exists()
    assert (source / "input.txt").read_text() == "hidden edit"


@pytest.mark.parametrize("staged", [False, True])
def test_dirty_source_is_rejected(source: Path, tmp_path: Path, staged: bool) -> None:
    (source / "input.txt").write_text("modified")
    if staged:
        subprocess.run(["git", "-C", str(source), "add", "input.txt"], check=True)
    with pytest.raises(rom_builder.BuildError, match="clean pinned checkout"):
        rom_builder.export_source(source, tmp_path / "exported")


def test_wrong_revision_is_rejected_before_export(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rom_builder, "PINNED_REVISION", "0" * 40)
    exported = tmp_path / "exported"
    with pytest.raises(rom_builder.BuildError, match="source HEAD must be"):
        rom_builder.export_source(source, exported)
    assert not exported.exists()


def test_build_failure_preserves_existing_output(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    for name in (*rom_builder.ARTIFACTS, "oracle-extra.txt"):
        (output / name).write_text("existing")

    def fail(_build: Path) -> None:
        raise rom_builder.BuildError("bad ROM hash")

    monkeypatch.setattr(rom_builder, "compile_rom", fail)
    with pytest.raises(rom_builder.BuildError, match="bad ROM hash"):
        rom_builder.build_rom(source, output)
    for name in (*rom_builder.ARTIFACTS, "oracle-extra.txt"):
        assert (output / name).read_text() == "existing"


def test_verified_build_publishes_artifacts_and_preserves_other_files(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "oracle-extra.txt").write_text("keep")

    def compile_fixture(build: Path) -> None:
        assert (build / "input.txt").read_text() == "canonical source\n"
        (build / "pokered.gbc").write_bytes(b"verified ROM")
        (build / "pokered.sym").write_text("debug symbols")

    monkeypatch.setattr(rom_builder, "compile_rom", compile_fixture)
    rom_builder.build_rom(source, output)
    assert (output / "pokered.gbc").read_bytes() == b"verified ROM"
    assert (output / "pokered.sym").read_text() == "debug symbols"
    assert (output / "oracle-extra.txt").read_text() == "keep"
    assert not list(output.glob(".rom-publish-*"))


def test_wrong_rom_hash_fails_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pokered.gbc").write_bytes(b"incorrect ROM")
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: None)
    with pytest.raises(rom_builder.BuildError, match="SHA-1 mismatch"):
        rom_builder.compile_rom(tmp_path)


@pytest.mark.parametrize("empty_symbols", [False, True])
def test_symbols_are_required_for_valid_rom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, empty_symbols: bool
) -> None:
    (tmp_path / "pokered.gbc").write_bytes(b"canonical fixture")
    if empty_symbols:
        (tmp_path / "pokered.sym").touch()
    monkeypatch.setattr(rom_builder, "RED_SHA1", hashlib.sha1(b"canonical fixture").hexdigest())
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: None)
    with pytest.raises(rom_builder.BuildError, match="debug symbols"):
        rom_builder.compile_rom(tmp_path)


def test_publication_staging_failure_preserves_existing_artifacts(tmp_path: Path) -> None:
    build = tmp_path / "build"
    output = tmp_path / "output"
    build.mkdir()
    output.mkdir()
    # A missing ROM fails after symbols have already been staged.
    (build / "pokered.sym").write_text("new symbols")
    for name in rom_builder.ARTIFACTS:
        (output / name).write_text("existing")
    with pytest.raises(FileNotFoundError):
        rom_builder.publish(build, output)
    for name in rom_builder.ARTIFACTS:
        assert (output / name).read_text() == "existing"
    assert not list(output.glob(".rom-publish-*"))


def test_cli_source_failure_is_nonzero_and_structured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "output"
    monkeypatch.setattr(
        sys,
        "argv",
        ["rom_builder", "--source", str(tmp_path / "missing"), "--output", str(output)],
    )
    assert rom_builder.main() == 1
    messages = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert messages[-1]["event"] == "rom_build"
    assert messages[-1]["outcome"] == "failure"
    assert messages[-1]["output"] == str(output)
    assert "clean pinned checkout" in messages[-1]["error"]
    assert not (output / "pokered.gbc").exists()
