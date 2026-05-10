"""In-memory symbol lookup for fast edge resolution during indexing."""

from __future__ import annotations

from dataclasses import dataclass, field

from codeidx.languages.base import SymbolRow


@dataclass
class SymbolIndex:
    """Maps symbol ids to metadata and supports the same resolution rules as SQL lookups."""

    _symbol_file: dict[int, int] = field(default_factory=dict)
    _symbol_kind: dict[int, str] = field(default_factory=dict)
    _symbol_qname: dict[int, str] = field(default_factory=dict)
    _by_qname: dict[str, list[int]] = field(default_factory=dict)
    _by_name: dict[str, list[int]] = field(default_factory=dict)
    _type_like_by_name: dict[str, list[int]] = field(default_factory=dict)

    def register_symbols(
        self, file_id: int, symbols: list[SymbolRow], ids: list[int]
    ) -> None:
        for sym, sid in zip(symbols, ids, strict=True):
            self._symbol_file[sid] = file_id
            self._symbol_kind[sid] = sym.kind
            self._symbol_qname[sid] = sym.qualified_name
            self._by_qname.setdefault(sym.qualified_name, []).append(sid)
            self._by_name.setdefault(sym.name, []).append(sid)
            if sym.kind in ("type", "interface", "enum", "delegate"):
                self._type_like_by_name.setdefault(sym.name, []).append(sid)

    def evict_file(self, conn_symbols_rows: list[tuple[int, str, str, str]]) -> None:
        """Remove symbols listed as (id, qualified_name, name, kind) from the index."""
        for sid, qn, nm, kind in conn_symbols_rows:
            self._evict_one(int(sid), qn, nm, kind)

    def _evict_one(self, sid: int, qn: str, nm: str, kind: str) -> None:
        self._symbol_file.pop(sid, None)
        self._symbol_kind.pop(sid, None)
        self._symbol_qname.pop(sid, None)
        self._remove_from_list(self._by_qname, qn, sid)
        self._remove_from_list(self._by_name, nm, sid)
        if kind in ("type", "interface", "enum", "delegate"):
            self._remove_from_list(self._type_like_by_name, nm, sid)

    @staticmethod
    def _remove_from_list(d: dict[str, list[int]], key: str, sid: int) -> None:
        if key not in d:
            return
        d[key] = [x for x in d[key] if x != sid]
        if not d[key]:
            del d[key]

    def kind(self, symbol_id: int) -> str | None:
        return self._symbol_kind.get(symbol_id)

    def resolve_symbol_id(
        self,
        project_file_ids: set[int],
        name: str | None,
        qualified_guess: str | None,
    ) -> tuple[int | None, str]:
        if not name and not qualified_guess:
            return None, "unresolved"
        if qualified_guess:
            ids = self._by_qname.get(qualified_guess, [])
            if len(ids) == 1:
                return ids[0], "exact"
            if project_file_ids and ids:
                for sid in ids:
                    fid = self._symbol_file.get(sid)
                    if fid is not None and fid in project_file_ids:
                        return sid, "heuristic"
        cand_name = name or (
            qualified_guess.split(".")[-1] if qualified_guess else ""
        )
        if not cand_name:
            return None, "unresolved"
        rows_ids = self._by_name.get(cand_name, [])
        if project_file_ids:
            rows_ids = [
                sid
                for sid in rows_ids
                if self._symbol_file.get(sid) in project_file_ids
            ]
        if not rows_ids:
            return None, "unresolved"
        if len(rows_ids) == 1:
            return rows_ids[0], "heuristic"
        if qualified_guess:
            for sid in rows_ids:
                qn = self._symbol_qname.get(sid)
                if qn and (
                    qualified_guess in qn or qn.endswith("." + cand_name)
                ):
                    return sid, "heuristic"
        return rows_ids[0], "heuristic"

    def resolve_string_ref_dst(self, literal: str) -> tuple[int | None, str]:
        ids = self._type_like_by_name.get(literal, [])
        if len(ids) != 1:
            return None, "unresolved"
        return ids[0], "heuristic"

    def resolve_unique_interface_by_name(
        self, name: str, scope_file_ids: set[int]
    ) -> int | None:
        cand_ids = self._by_name.get(name, [])
        iface_ids = [sid for sid in cand_ids if self._symbol_kind.get(sid) == "interface"]
        if not iface_ids:
            return None
        if len(iface_ids) == 1:
            return iface_ids[0]
        if scope_file_ids:
            in_scope = [
                sid
                for sid in iface_ids
                if self._symbol_file.get(sid) in scope_file_ids
            ]
            if len(in_scope) == 1:
                return in_scope[0]
        return None
