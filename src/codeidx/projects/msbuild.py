from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CsprojInfo:
    path: Path
    name: str
    project_references: list[Path] = field(default_factory=list)
    package_references: list[str] = field(default_factory=list)
    domain: str | None = None


_SLN_PROJECT = re.compile(
    r'Project\("\{[A-Fa-f0-9-]+\}"\)\s*=\s*"(?P<name>[^"]+)"\s*,\s*"(?P<path>[^"]+)"\s*,\s*"\{(?P<guid>[A-Fa-f0-9-]+)\}"',
)


def parse_sln(sln_path: Path) -> list[tuple[str, Path]]:
    """Return list of (project_name, absolute_path_to_csproj)."""
    root = sln_path.parent.resolve()
    text = sln_path.read_text(encoding="utf-8", errors="replace")
    out: list[tuple[str, Path]] = []
    for m in _SLN_PROJECT.finditer(text):
        name = m.group("name")
        rel = m.group("path").replace("\\", "/")
        p = (root / rel).resolve()
        if p.suffix.lower() in (".csproj", ".vbproj", ".fsproj"):
            out.append((name, p))
    return out


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _domain_from_root_namespace(root_namespace: str | None) -> str | None:
    if not root_namespace or not root_namespace.strip():
        return None
    first = root_namespace.strip().split(".", 1)[0].strip()
    return first or None


def parse_csproj(csproj_path: Path) -> CsprojInfo:
    tree = ET.parse(csproj_path)
    root_el = tree.getroot()
    name = csproj_path.stem
    proj_refs: list[Path] = []
    pkg_refs: list[str] = []
    root_namespace: str | None = None
    base = csproj_path.parent.resolve()
    for el in root_el.iter():
        tag = _strip_ns(el.tag)
        if tag == "RootNamespace" and el.text and el.text.strip():
            if root_namespace is None:
                root_namespace = el.text.strip()
        elif tag == "ProjectReference":
            inc = el.attrib.get("Include")
            if inc:
                proj_refs.append((base / inc).resolve())
        elif tag == "PackageReference":
            pkg = el.attrib.get("Include")
            if pkg:
                pkg_refs.append(pkg)
    domain = _domain_from_root_namespace(root_namespace)
    return CsprojInfo(
        path=csproj_path.resolve(),
        name=name,
        project_references=proj_refs,
        package_references=pkg_refs,
        domain=domain,
    )


def discover_solution_files(repo_root: Path) -> list[Path]:
    return sorted(repo_root.rglob("*.sln"))


def discover_csproj_files(repo_root: Path) -> list[Path]:
    return sorted(p for p in repo_root.rglob("*.csproj") if p.is_file())


def collect_csproj_infos_from_solutions(
    sln_paths: list[Path],
    *,
    missing_csproj: list[str] | None = None,
) -> list[CsprojInfo]:
    """Load and parse all projects referenced by the given solutions, de-duplicated by .csproj path.

    Used to merge a monorepo with many .sln files into one project graph in a single
    run_index pass (stronger cross-project resolution than --no-sln or an interactive
    single-solution pick).

    Entries in a .sln that point at a path with no file on disk are skipped. When
    ``missing_csproj`` is provided, each skip is appended as a human-readable string.
    """
    seen: set[str] = set()
    out: list[CsprojInfo] = []
    for sp in sln_paths:
        for _name, cpp in parse_sln(sp.resolve()):
            if cpp.suffix.lower() != ".csproj":
                continue
            key = str(cpp.resolve())
            if key in seen:
                continue
            if not cpp.is_file():
                if missing_csproj is not None:
                    missing_csproj.append(
                        f"solution {sp.name} lists missing .csproj: {cpp}"
                    )
                continue
            seen.add(key)
            out.append(parse_csproj(cpp))
    return out

