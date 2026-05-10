from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pathspec.gitignore import GitIgnoreSpec

from codeidx.indexer.ignore import build_spec, is_ignored


@dataclass(frozen=True)
class FileStat:
    path: Path
    size: int
    mtime_ns: int
    sha256: str


def hash_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def stat_file(path: Path) -> tuple[int, int]:
    st = path.stat()
    size = int(st.st_size)
    # nanosecond mtime when available (Py 3.12+); else seconds * 1e9
    mtime_ns = getattr(st, "st_mtime_ns", None)
    if mtime_ns is None:
        mtime_ns = int(st.st_mtime * 1_000_000_000)
    return size, int(mtime_ns)


def iter_files(
    repo_root: Path,
    spec: GitIgnoreSpec,
    extensions: set[str] | None = None,
) -> Iterator[Path]:
    root = repo_root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        dp = Path(dirpath)
        dirnames[:] = [
            d
            for d in dirnames
            if not is_ignored(spec, root, dp / d)
        ]
        for name in filenames:
            p = dp / name
            if is_ignored(spec, root, p):
                continue
            if extensions is not None:
                if p.suffix.lower() not in extensions:
                    continue
            yield p


def file_fingerprint(path: Path, *, skip_hash: bool = False) -> FileStat:
    size, mtime_ns = stat_file(path)
    digest = "" if skip_hash else hash_file(path)
    return FileStat(path=path, size=size, mtime_ns=mtime_ns, sha256=digest)
