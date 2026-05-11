"""Manchester OWL Syntax parser: lark grammar → typed AST nodes."""
from __future__ import annotations

import re
from dataclasses import dataclass

from lark import Lark, Token, Tree, UnexpectedInput

# ── AST node types ─────────────────────────────────────────────────────────────

@dataclass
class NamedClass:
    ref: str             # label text, CURIE, or full IRI
    curie: str | None    # CURIE hint if disambiguated, else None


@dataclass
class And:
    left: "ASTNode"
    right: "ASTNode"


@dataclass
class Or:
    left: "ASTNode"
    right: "ASTNode"


@dataclass
class Not:
    operand: "ASTNode"


@dataclass
class SomeValuesFrom:
    property_ref: NamedClass
    filler: "ASTNode"


@dataclass
class AllValuesFrom:
    property_ref: NamedClass
    filler: "ASTNode"


@dataclass
class HasValue:
    property_ref: NamedClass
    value_ref: NamedClass


@dataclass
class HasSelf:
    property_ref: NamedClass


@dataclass
class MinCardinality:
    property_ref: NamedClass
    cardinality: int
    filler: "ASTNode"


@dataclass
class MaxCardinality:
    property_ref: NamedClass
    cardinality: int
    filler: "ASTNode"


@dataclass
class ExactCardinality:
    property_ref: NamedClass
    cardinality: int
    filler: "ASTNode"


ASTNode = (
    NamedClass | And | Or | Not
    | SomeValuesFrom | AllValuesFrom | HasValue | HasSelf
    | MinCardinality | MaxCardinality | ExactCardinality
)


class ParseError(ValueError):
    pass


# ── Grammar ────────────────────────────────────────────────────────────────────

_GRAMMAR = r"""
    expression   : or_expr
    or_expr      : and_expr ("or" and_expr)*
    and_expr     : not_expr ("and" not_expr)*
    not_expr     : "not" primary -> not_node
                 | primary
    primary      : "(" expression ")" -> paren
                 | restriction
                 | entity_ref     -> named_class_node

    restriction  : entity_ref "some"    expression     -> some_node
                 | entity_ref "only"    expression     -> only_node
                 | entity_ref "value"   entity_ref     -> value_node
                 | entity_ref "Self"                   -> self_node
                 | entity_ref "min"     INT expression -> min_node
                 | entity_ref "max"     INT expression -> max_node
                 | entity_ref "exactly" INT expression -> exactly_node

    entity_ref   : QUOTED_LABEL
                 | CURIE
                 | FULL_IRI

    QUOTED_LABEL : "'" /[^']+/ "'"
    CURIE        : /[A-Za-z_][A-Za-z0-9_\-]*:[A-Za-z0-9_\-\.]+/
    FULL_IRI     : "<" /[^>]+/ ">"
    INT          : /[0-9]+/

    %ignore /\s+/
"""

_PARSER = Lark(_GRAMMAR, start="expression", parser="earley", ambiguity="resolve")

_DISAMBIG_RE = re.compile(r"^(.+?)\s+\(([A-Za-z_][A-Za-z0-9_\-]*:[A-Za-z0-9_\-\.]+)\)$")


def _entity_ref_to_named_class(tree: Tree) -> NamedClass:
    token = tree.children[0]
    raw = str(token)
    if isinstance(token, Token) and token.type == "QUOTED_LABEL":
        inner = raw[1:-1]  # strip surrounding '...'
        m = _DISAMBIG_RE.match(inner)
        if m:
            return NamedClass(ref=m.group(1), curie=m.group(2))
        return NamedClass(ref=inner, curie=None)
    if isinstance(token, Token) and token.type == "FULL_IRI":
        return NamedClass(ref=raw[1:-1], curie=None)  # strip < >
    return NamedClass(ref=raw, curie=None)  # CURIE


def _build(tree: Tree) -> ASTNode:
    if tree.data == "expression":
        return _build(tree.children[0])

    if tree.data == "or_expr":
        children = [_build(c) for c in tree.children]
        result = children[0]
        for c in children[1:]:
            result = Or(result, c)
        return result

    if tree.data == "and_expr":
        children = [_build(c) for c in tree.children]
        result = children[0]
        for c in children[1:]:
            result = And(result, c)
        return result

    if tree.data == "not_node":
        return Not(_build(tree.children[0]))

    if tree.data == "paren":
        return _build(tree.children[0])

    if tree.data == "named_class_node":
        return _entity_ref_to_named_class(tree.children[0])

    if tree.data == "some_node":
        return SomeValuesFrom(_entity_ref_to_named_class(tree.children[0]), _build(tree.children[1]))

    if tree.data == "only_node":
        return AllValuesFrom(_entity_ref_to_named_class(tree.children[0]), _build(tree.children[1]))

    if tree.data == "value_node":
        return HasValue(_entity_ref_to_named_class(tree.children[0]), _entity_ref_to_named_class(tree.children[1]))

    if tree.data == "self_node":
        return HasSelf(_entity_ref_to_named_class(tree.children[0]))

    if tree.data == "min_node":
        return MinCardinality(_entity_ref_to_named_class(tree.children[0]), int(tree.children[1]), _build(tree.children[2]))

    if tree.data == "max_node":
        return MaxCardinality(_entity_ref_to_named_class(tree.children[0]), int(tree.children[1]), _build(tree.children[2]))

    if tree.data == "exactly_node":
        return ExactCardinality(_entity_ref_to_named_class(tree.children[0]), int(tree.children[1]), _build(tree.children[2]))

    if tree.data == "restriction":
        return _build(tree.children[0])

    if tree.data == "primary":
        return _build(tree.children[0])

    if tree.data == "not_expr":
        return _build(tree.children[0])

    raise ParseError(f"Unknown tree node: {tree.data}")


def parse(text: str) -> ASTNode:
    """Parse a MOS expression string into a typed AST. Raises ParseError on failure."""
    try:
        tree = _PARSER.parse(text)
        return _build(tree)
    except UnexpectedInput as exc:
        raise ParseError(str(exc)) from exc
    except Exception as exc:
        raise ParseError(str(exc)) from exc
