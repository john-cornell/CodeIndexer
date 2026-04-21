from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Node, Tree
from tree_sitter_languages import get_parser

from codeidx.languages.base import EdgeRow, LanguageHandler, ParseResult, SymbolRow


def _txt(src: bytes, node: Node | None) -> str:
    if node is None:
        return ""
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _span_1based(node: Node) -> tuple[int, int, int, int]:
    sl = int(node.start_point[0]) + 1
    el = int(node.end_point[0]) + 1
    sc = int(node.start_point[1])
    ec = int(node.end_point[1])
    return sl, el, sc, ec


def _child_named(node: Node, name: str) -> Node | None:
    for c in node.children:
        if c.type == name:
            return c
    return None


def _find_field(node: Node, field: str) -> Node | None:
    n = node.child_by_field_name(field)
    return n


@dataclass
class _Scope:
    namespaces: list[str]
    types: list[str]

    def clone(self) -> _Scope:
        return _Scope(list(self.namespaces), list(self.types))

    def qualified_prefix(self) -> str:
        parts = [p for p in self.namespaces if p] + [p for p in self.types if p]
        return ".".join(parts)


class CSharpHandler(LanguageHandler):
    name = "csharp"

    def __init__(self) -> None:
        # tree_sitter / tree-sitter-languages emit FutureWarning for Language(path, name) until upgraded.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=FutureWarning)
            self._parser = get_parser("c_sharp")

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() == ".cs"

    def parse_file(self, path: Path, source: bytes) -> ParseResult:
        tree = self._parser.parse(source)
        return _walk(tree, source)


def _walk(tree: Tree, source: bytes) -> ParseResult:
    root = tree.root_node
    pr = ParseResult()
    scope = _Scope([], [])
    _walk_node(root, source, scope, pr)
    return pr


def _type_name_from_node(src: bytes, node: Node | None) -> str:
    if node is None:
        return ""
    if node.type == "identifier":
        return _txt(src, node)
    if node.type == "qualified_name":
        return _txt(src, node).replace(" ", "")
    return _txt(src, node).strip()


def _walk_node(node: Node, src: bytes, scope: _Scope, pr: ParseResult) -> None:
    t = node.type

    if t == "namespace_declaration":
        name_node = _find_field(node, "name")
        nm = _type_name_from_node(src, name_node)
        ns = scope.clone()
        if nm:
            ns.namespaces.append(nm)
        body = _find_field(node, "body")
        if body:
            for ch in body.children:
                _walk_node(ch, src, ns, pr)
        return

    if t == "file_scoped_namespace_declaration":
        name_node = _find_field(node, "name")
        nm = _type_name_from_node(src, name_node)
        ns = scope.clone()
        if nm:
            ns.namespaces.append(nm)
        for ch in node.children:
            if ch.type in ("using_directive", "extern_alias_directive"):
                _walk_node(ch, src, ns, pr)
            elif ch.type not in (";",):
                _walk_node(ch, src, ns, pr)
        return

    if t == "using_directive":
        static_kw = any(c.type == "static" for c in node.children)
        name_node = _find_field(node, "name")
        alias_node = _find_field(node, "alias")
        nm = _type_name_from_node(src, name_node)
        sl, el, sc, ec = _span_1based(node)
        meta = {"using": nm, "static": static_kw}
        if alias_node:
            meta["alias"] = _txt(src, alias_node)
        pr.edges.append(
            EdgeRow(
                src_symbol_name=None,
                dst_qualified_guess=nm or None,
                edge_type="imports",
                confidence="exact" if nm else "unresolved",
                ref_start_line=sl,
                ref_start_col=sc,
                ref_end_line=el,
                ref_end_col=ec,
                meta=meta,
            )
        )
        return

    if t in (
        "class_declaration",
        "struct_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
        "record_struct_declaration",
    ):
        name_node = _find_field(node, "name")
        nm = _type_name_from_node(src, name_node)
        sc2 = scope.clone()
        if nm:
            sc2.types.append(nm)
        q = sc2.qualified_prefix()
        sl, el, sc, ec = _span_1based(node)
        kind = "type"
        if t == "interface_declaration":
            kind = "interface"
        elif t == "enum_declaration":
            kind = "enum"
        pr.symbols.append(
            SymbolRow(
                kind=kind,
                name=nm or "<anonymous>",
                qualified_name=q,
                span_start_line=sl,
                span_end_line=el,
                span_start_col=sc,
                span_end_col=ec,
                ts_node_id=str(node.id),
            )
        )
        bases = _find_field(node, "bases")
        if bases:
            _emit_inheritance_edges(src, bases, q, sl, sc, pr)
        body = _find_field(node, "body")
        if body:
            for ch in body.children:
                _walk_node(ch, src, sc2, pr)
        return

    if t == "method_declaration":
        name_node = _find_field(node, "name")
        nm = _type_name_from_node(src, name_node)
        sc2 = scope.clone()
        q = (sc2.qualified_prefix() + ("." + nm if nm else "")).strip(".")
        sl, el, sc, ec = _span_1based(node)
        pr.symbols.append(
            SymbolRow(
                kind="method",
                name=nm or "<anonymous>",
                qualified_name=q,
                span_start_line=sl,
                span_end_line=el,
                span_start_col=sc,
                span_end_col=ec,
                ts_node_id=str(node.id),
            )
        )
        body = _find_field(node, "body")
        if body:
            _collect_invocations(body, src, sc2, pr, q)
        return

    if t == "constructor_declaration":
        name_node = _find_field(node, "name")
        nm = _type_name_from_node(src, name_node)
        sc2 = scope.clone()
        q = (sc2.qualified_prefix() + ("." + nm if nm else "")).strip(".")
        sl, el, sc, ec = _span_1based(node)
        pr.symbols.append(
            SymbolRow(
                kind="constructor",
                name=nm or ".ctor",
                qualified_name=q,
                span_start_line=sl,
                span_end_line=el,
                span_start_col=sc,
                span_end_col=ec,
                ts_node_id=str(node.id),
            )
        )
        body = _find_field(node, "body")
        if body:
            _collect_invocations(body, src, sc2, pr, q)
        return

    if t == "property_declaration":
        nm_node = _child_named(node, "name") or _find_field(node, "name")
        if nm_node is None:
            for c in node.children:
                if c.type == "identifier":
                    nm_node = c
                    break
        nm = _type_name_from_node(src, nm_node)
        sc2 = scope.clone()
        q = (sc2.qualified_prefix() + ("." + nm if nm else "")).strip(".")
        sl, el, sc, ec = _span_1based(node)
        pr.symbols.append(
            SymbolRow(
                kind="property",
                name=nm or "<anonymous>",
                qualified_name=q,
                span_start_line=sl,
                span_end_line=el,
                span_start_col=sc,
                span_end_col=ec,
                ts_node_id=str(node.id),
            )
        )
        for ch in node.children:
            if ch.type in ("accessor_list", "arrow_expression_clause"):
                _walk_node(ch, src, sc2, pr)
        return

    if t == "field_declaration":
        for c in node.children:
            if c.type == "variable_declaration":
                for v in c.children:
                    if v.type == "variable_declarator":
                        id_node = _find_field(v, "name")
                        nm = _type_name_from_node(src, id_node)
                        sc2 = scope.clone()
                        q = (sc2.qualified_prefix() + ("." + nm if nm else "")).strip(".")
                        sl, el, sc, ec = _span_1based(v)
                        pr.symbols.append(
                            SymbolRow(
                                kind="field",
                                name=nm or "<anonymous>",
                                qualified_name=q,
                                span_start_line=sl,
                                span_end_line=el,
                                span_start_col=sc,
                                span_end_col=ec,
                                ts_node_id=str(v.id),
                            )
                        )
        return

    if t == "enum_member_declaration":
        nm_node = _find_field(node, "name")
        nm = _type_name_from_node(src, nm_node)
        sc2 = scope.clone()
        q = (sc2.qualified_prefix() + ("." + nm if nm else "")).strip(".")
        sl, el, sc, ec = _span_1based(node)
        pr.symbols.append(
            SymbolRow(
                kind="enum_member",
                name=nm or "<anonymous>",
                qualified_name=q,
                span_start_line=sl,
                span_end_line=el,
                span_start_col=sc,
                span_end_col=ec,
                ts_node_id=str(node.id),
            )
        )
        return

    if t == "delegate_declaration":
        name_node = _find_field(node, "name")
        nm = _type_name_from_node(src, name_node)
        sc2 = scope.clone()
        q = (sc2.qualified_prefix() + ("." + nm if nm else "")).strip(".")
        sl, el, sc, ec = _span_1based(node)
        pr.symbols.append(
            SymbolRow(
                kind="delegate",
                name=nm or "<anonymous>",
                qualified_name=q,
                span_start_line=sl,
                span_end_line=el,
                span_start_col=sc,
                span_end_col=ec,
                ts_node_id=str(node.id),
            )
        )
        return

    for ch in node.children:
        _walk_node(ch, src, scope, pr)


def _emit_inheritance_edges(
    src: bytes,
    bases: Node,
    type_q: str,
    type_sl: int,
    type_sc: int,
    pr: ParseResult,
) -> None:
    items: list[Node] = []
    for ch in bases.children:
        if ch.type in (",", ":", "<", ">", "(", ")"):
            continue
        if ch.type == "base_list":
            continue
        t = _txt(src, ch).strip()
        if not t or t == ":":
            continue
        items.append(ch)
    for idx, ch in enumerate(items):
        base_txt = _txt(src, ch).strip()
        sl, el, sc, ec = _span_1based(ch)
        edge_t = "inherits" if idx == 0 else "implements"
        pr.edges.append(
            EdgeRow(
                src_symbol_name=type_q,
                dst_qualified_guess=base_txt,
                edge_type=edge_t,
                confidence="heuristic",
                ref_start_line=sl,
                ref_start_col=sc,
                ref_end_line=el,
                ref_end_col=ec,
                meta={"base_text": base_txt, "base_index": idx},
            )
        )


def _collect_invocations(body: Node, src: bytes, scope: _Scope, pr: ParseResult, owner_q: str) -> None:
    stack = [body]
    while stack:
        n = stack.pop()
        if n.type == "invocation_expression":
            expr = _find_field(n, "function")
            callee = _callee_text(src, expr)
            sl, el, sc, ec = _span_1based(n)
            simple = callee.split(".")[-1].split("::")[-1] if callee else ""
            if simple.endswith(")"):
                simple = simple[: simple.rfind("(")]
            simple = simple.strip()
            pr.edges.append(
                EdgeRow(
                    src_symbol_name=owner_q,
                    dst_qualified_guess=callee or simple or None,
                    edge_type="calls",
                    confidence="unresolved",
                    ref_start_line=sl,
                    ref_start_col=sc,
                    ref_end_line=el,
                    ref_end_col=ec,
                    meta={"callee_text": callee, "callee_simple": simple},
                )
            )
        for ch in n.children:
            stack.append(ch)


def _callee_text(src: bytes, expr: Node | None) -> str:
    if expr is None:
        return ""
    if expr.type == "identifier":
        return _txt(src, expr)
    if expr.type == "member_access_expression":
        return _txt(src, expr).replace(" ", "")
    if expr.type == "member_binding_expression":
        return _txt(src, expr)
    if expr.type == "invocation_expression":
        inner = _find_field(expr, "function")
        return _callee_text(src, inner)
    return _txt(src, expr).replace(" ", "")
