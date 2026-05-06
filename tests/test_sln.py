from __future__ import annotations

from pathlib import Path

from codeidx.projects.msbuild import collect_csproj_infos_from_solutions, parse_sln


def test_parse_sln(tmp_path: Path) -> None:
    sln = tmp_path / "x.sln"
    sln.write_text(
        """
Microsoft Visual Studio Solution File, Format Version 12.00
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Lib", "src\\\\Lib\\\\Lib.csproj", "{11111111-1111-1111-1111-111111111111}"
EndProject
""",
        encoding="utf-8",
    )
    (tmp_path / "src" / "Lib").mkdir(parents=True)
    cs = tmp_path / "src" / "Lib" / "Lib.csproj"
    cs.write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>', encoding="utf-8")
    projects = parse_sln(sln)
    assert len(projects) == 1
    assert projects[0][0] == "Lib"
    assert projects[0][1] == cs.resolve()


def test_collect_csproj_infos_dedupes_across_solutions(tmp_path: Path) -> None:
    """Two .sln files referencing the same .csproj yield a single CsprojInfo."""
    (tmp_path / "src" / "Lib").mkdir(parents=True)
    cs = tmp_path / "src" / "Lib" / "Lib.csproj"
    cs.write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>', encoding="utf-8")
    line = f'Project("{{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}}") = "Lib", "src\\\\Lib\\\\Lib.csproj", "{{11111111-1111-1111-1111-111111111111}}"\n'
    for name in ("a", "b"):
        sln = tmp_path / f"{name}.sln"
        sln.write_text(
            "Microsoft Visual Studio Solution File, Format Version 12.00\n"
            + line
            + "EndProject\n",
            encoding="utf-8",
        )
    infos = collect_csproj_infos_from_solutions(
        [tmp_path / "a.sln", tmp_path / "b.sln"]
    )
    assert len(infos) == 1
    assert infos[0].path == cs.resolve()


def test_collect_csproj_infos_skips_missing_csproj_from_sln(tmp_path: Path) -> None:
    sln = tmp_path / "x.sln"
    sln.write_text(
        "Microsoft Visual Studio Solution File, Format Version 12.00\n"
        'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Gone", '
        '"missing\\\\Gone.csproj", "{22222222-2222-2222-2222-222222222222}"\n'
        "EndProject\n",
        encoding="utf-8",
    )
    missing: list[str] = []
    infos = collect_csproj_infos_from_solutions([sln], missing_csproj=missing)
    assert infos == []
    assert len(missing) == 1
    assert "missing" in missing[0]
