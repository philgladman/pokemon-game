from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import stat
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .parsers import ParseError


def read_git_revision(root: Path) -> str:
    """Resolve HEAD without requiring a Git executable in runtime images."""

    git_dir = _git_directory(root)
    head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    if re.fullmatch(r"[0-9a-f]{40}", head):
        return head
    if not head.startswith("ref: "):
        raise ParseError("pret/pokered HEAD is malformed")
    reference = head.removeprefix("ref: ")
    if re.fullmatch(r"refs/[A-Za-z0-9._/-]+", reference) is None or ".." in Path(reference).parts:
        raise ParseError("pret/pokered HEAD reference is malformed")
    loose_ref = git_dir / reference
    if loose_ref.is_file():
        revision = loose_ref.read_text(encoding="utf-8").strip()
    else:
        revision = _packed_reference(git_dir / "packed-refs", reference)
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ParseError("pret/pokered HEAD does not resolve to a full commit revision")
    return revision


def validate_clean_checkout(root: Path, expected_tree: str) -> None:
    """Verify tracked bytes and the staged tree using Git's canonical index."""

    git_dir = _git_directory(root)
    index_path = git_dir / "index"
    try:
        entries = _read_index(index_path)
    except OSError as error:
        raise ParseError(f"unable to read pret/pokered index at {index_path}: {error}") from error

    actual_tree = _index_tree(entries)
    if actual_tree != expected_tree:
        raise ParseError(f"pret/pokered index differs from pinned tree {expected_tree} at {root}")

    attributes_entry = next(
        (entry for entry in entries if entry.path_parts == (b".gitattributes",)),
        None,
    )
    if attributes_entry is None:
        raise ParseError(f"pret/pokered index has no tracked .gitattributes at {root}")
    attributes_content = _validate_worktree_entry(root, attributes_entry, normalize_text=False)
    attributes = _TextAttributes.parse(attributes_content, root / ".gitattributes")
    for entry in entries:
        if entry is attributes_entry:
            continue
        _validate_worktree_entry(
            root,
            entry,
            normalize_text=attributes.is_text(entry),
        )


@dataclass(frozen=True)
class _IndexEntry:
    path_parts: tuple[bytes, ...]
    mode: int
    object_id: bytes

    @property
    def display_path(self) -> str:
        return "/".join(os.fsdecode(part) for part in self.path_parts)


@dataclass
class _TreeNode:
    files: dict[bytes, _IndexEntry] = field(default_factory=dict)
    directories: dict[bytes, _TreeNode] = field(default_factory=dict)


@dataclass(frozen=True)
class _TextRule:
    pattern: str
    text: bool


@dataclass(frozen=True)
class _TextAttributes:
    rules: tuple[_TextRule, ...]

    @classmethod
    def parse(cls, content: bytes, path: Path) -> _TextAttributes:
        try:
            lines = content.decode("utf-8").splitlines()
        except UnicodeDecodeError as error:
            raise ParseError(f"tracked pret/pokered attributes are not UTF-8 at {path}") from error
        rules: list[_TextRule] = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split()
            if len(fields) < 2:
                raise ParseError(f"unsupported tracked pret/pokered attribute rule at {path}")
            text: bool | None = None
            for attribute in fields[1:]:
                if attribute == "text":
                    text = True
                elif attribute in ("-text", "binary"):
                    text = False
            if text is not None:
                rules.append(_TextRule(fields[0], text))
        return cls(tuple(rules))

    def is_text(self, entry: _IndexEntry) -> bool:
        path = entry.display_path
        result = False
        for rule in self.rules:
            candidate = path if "/" in rule.pattern else entry.display_path.rsplit("/", 1)[-1]
            if fnmatch.fnmatchcase(candidate, rule.pattern):
                result = rule.text
        return result


def _git_directory(root: Path) -> Path:
    git_marker = root / ".git"
    if git_marker.is_dir():
        return git_marker
    elif git_marker.is_file():
        marker = git_marker.read_text(encoding="utf-8").strip()
        if not marker.startswith("gitdir: "):
            raise ParseError("unsupported .git file")
        return (root / marker.removeprefix("gitdir: ")).resolve()
    raise ParseError(f"pret/pokered source root is not a Git checkout: {root}")


def _packed_reference(path: Path, reference: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(("#", "^")):
            continue
        revision, separator, candidate = line.partition(" ")
        if separator and candidate == reference:
            return revision
    raise ParseError(f"pret/pokered Git reference is missing: {reference}")


def _read_index(path: Path) -> list[_IndexEntry]:
    content = path.read_bytes()
    if len(content) < 32 or content[:4] != b"DIRC":
        raise ParseError(f"pret/pokered Git index is malformed: {path}")
    payload, checksum = content[:-20], content[-20:]
    # Git index checksums and object IDs are defined as SHA-1 values.
    if hashlib.sha1(payload).digest() != checksum:
        raise ParseError(f"pret/pokered Git index checksum is invalid: {path}")
    version, entry_count = struct.unpack(">II", payload[4:12])
    if version not in (2, 3):
        raise ParseError(f"unsupported pret/pokered Git index version {version}: {path}")

    entries: list[_IndexEntry] = []
    offset = 12
    for _ in range(entry_count):
        entry_start = offset
        if offset + 62 > len(payload):
            raise ParseError(f"pret/pokered Git index entry is truncated: {path}")
        unpacked = struct.unpack(">10I20sH", payload[offset : offset + 62])
        mode, object_id, flags = unpacked[6], unpacked[10], unpacked[11]
        offset += 62
        if flags & 0x4000:
            if version < 3 or offset + 2 > len(payload):
                raise ParseError(f"pret/pokered Git index has invalid extended flags: {path}")
            offset += 2
        if flags & 0x3000:
            raise ParseError(f"pret/pokered Git index contains unresolved entries: {path}")
        path_end = payload.find(b"\0", offset)
        if path_end < 0:
            raise ParseError(f"pret/pokered Git index path is unterminated: {path}")
        raw_path = payload[offset:path_end]
        path_parts = tuple(raw_path.split(b"/"))
        if not raw_path or any(part in (b"", b".", b"..") for part in path_parts):
            raise ParseError(f"pret/pokered Git index contains an unsafe path: {path}")
        entries.append(_IndexEntry(path_parts, mode, object_id))
        entry_length = path_end + 1 - entry_start
        offset = entry_start + (entry_length + 7) // 8 * 8
    return entries


def _index_tree(entries: list[_IndexEntry]) -> str:
    root = _TreeNode()
    for entry in entries:
        node = root
        for directory in entry.path_parts[:-1]:
            if directory in node.files:
                raise ParseError("pret/pokered Git index contains a file/directory collision")
            node = node.directories.setdefault(directory, _TreeNode())
        filename = entry.path_parts[-1]
        if filename in node.directories or filename in node.files:
            raise ParseError("pret/pokered Git index contains duplicate paths")
        node.files[filename] = entry
    return _tree_object_id(root).hex()


def _tree_object_id(node: _TreeNode) -> bytes:
    records: list[tuple[bytes, bytes]] = []
    for name, entry in node.files.items():
        mode = _canonical_mode(entry.mode)
        records.append((name, f"{mode:o} ".encode() + name + b"\0" + entry.object_id))
    for name, child in node.directories.items():
        records.append((name + b"/", b"40000 " + name + b"\0" + _tree_object_id(child)))
    body = b"".join(record for _, record in sorted(records, key=lambda item: item[0]))
    return _git_object_id(b"tree", body)


def _canonical_mode(mode: int) -> int:
    kind = stat.S_IFMT(mode)
    if kind == stat.S_IFREG:
        return 0o100755 if mode & 0o111 else 0o100644
    if kind in (stat.S_IFLNK, 0o160000):
        return mode
    raise ParseError(f"pret/pokered Git index contains unsupported mode {mode:o}")


def _validate_worktree_entry(
    root: Path,
    entry: _IndexEntry,
    *,
    normalize_text: bool,
) -> bytes:
    relative = Path(*(os.fsdecode(part) for part in entry.path_parts))
    path = root / relative
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ParseError(f"tracked pret/pokered file is missing at {path}") from error
    except OSError as error:
        raise ParseError(
            f"unable to inspect tracked pret/pokered file at {path}: {error}"
        ) from error

    expected_kind = stat.S_IFMT(entry.mode)
    actual_kind = stat.S_IFMT(metadata.st_mode)
    if expected_kind != actual_kind:
        raise ParseError(f"tracked pret/pokered file type differs from index at {path}")
    if expected_kind == stat.S_IFREG:
        expected_executable = bool(entry.mode & 0o111)
        if bool(metadata.st_mode & 0o111) != expected_executable:
            raise ParseError(f"tracked pret/pokered file mode differs from index at {path}")
        try:
            content = path.read_bytes()
        except OSError as error:
            raise ParseError(
                f"unable to read tracked pret/pokered file at {path}: {error}"
            ) from error
    elif expected_kind == stat.S_IFLNK:
        content = os.fsencode(os.readlink(path))
    elif expected_kind == 0o160000:
        raise ParseError(f"tracked pret/pokered submodules are unsupported at {path}")
    else:
        raise ParseError(f"tracked pret/pokered file has unsupported mode at {path}")
    if normalize_text:
        content = content.replace(b"\r\n", b"\n")
    if _git_object_id(b"blob", content) != entry.object_id:
        raise ParseError(f"tracked pret/pokered file differs from index at {path}")
    return content


def _git_object_id(kind: bytes, content: bytes) -> bytes:
    header = kind + b" " + str(len(content)).encode() + b"\0"
    return hashlib.sha1(header + content).digest()
