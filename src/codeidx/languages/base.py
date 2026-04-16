from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SymbolRow:
    kind: str
    name: str
    qualified_name: str
    span_start_line: int
    span_end_line: int
    span_start_col: int
    span_end_col: int
    ts_node_id: str | None = None


@dataclass
class EdgeRow:
    src_symbol_name: str | None
    dst_qualified_guess: str | None
    edge_type: str
    confidence: str
    ref_start_line: int
    ref_start_col: int
    ref_end_line: int
    ref_end_col: int
    meta: dict | None = None


@dataclass
class ParseResult:
    symbols: list[SymbolRow] = field(default_factory=list)
    edges: list[EdgeRow] = field(default_factory=list)


class LanguageHandler(ABC):
    name: str

    @abstractmethod
    def can_handle(self, path: Path) -> bool:
        raise NotImplementedError

    @abstractmethod
    def parse_file(self, path: Path, source: bytes) -> ParseResult:
        raise NotImplementedError
