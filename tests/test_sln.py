from __future__ import annotations

from pathlib import Path

from codeidx.projects.msbuild import parse_sln


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
