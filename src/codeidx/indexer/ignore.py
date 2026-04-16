from __future__ import annotations

from pathlib import Path

from pathspec.gitignore import GitIgnoreSpec

DEFAULT_IGNORES = [
    "**/.git/**",
    "**/bin/**",
    "**/obj/**",
    "**/node_modules/**",
    "**/.vs/**",
    "**/packages/**",
    "**/__pycache__/**",
    "**/.venv/**",
    "**/venv/**",
    "**/dist/**",
    "**/build/**",
    "**/.idea/**",
    "**/.cursor/**",
    "**/*.dll",
    "**/*.exe",
    "**/*.pdb",
    "**/*.cache",
]


def read_gitignore_lines(repo_root: Path) -> list[str]:
    gi = repo_root / ".gitignore"
    if not gi.is_file():
        return []
    lines: list[str] = []
    for ln in gi.read_text(encoding="utf-8", errors="replace").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    return lines


def build_spec(
    repo_root: Path,
    extra_patterns: list[str] | None = None,
    *,
    use_gitignore: bool = True,
) -> GitIgnoreSpec:
    patterns = list(DEFAULT_IGNORES)
    if use_gitignore:
        patterns.extend(read_gitignore_lines(repo_root))
    if extra_patterns:
        patterns.extend(extra_patterns)
    return GitIgnoreSpec.from_lines(patterns)


def is_ignored(spec: GitIgnoreSpec, repo_root: Path, path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return True
    if rel.as_posix() == ".":
        return False
    return spec.match_file(rel.as_posix())
