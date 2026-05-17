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
                 | BARE_LABEL

    QUOTED_LABEL : "'" /[^']+/ "'"
    CURIE        : /[A-Za-z_][A-Za-z0-9_\-]*:[A-Za-z0-9_\-\.]+/
    FULL_IRI     : "<" /[^>]+/ ">"
    BARE_LABEL   : /(?!(and|or|not|some|only|value|Self|min|max|exactly)\b)[A-Za-z_][A-Za-z0-9_]*/
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
    return NamedClass(ref=raw, curie=None)  # CURIE or BARE_LABEL


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


# ── Partial parse for autocomplete ────────────────────────────────────────────

@dataclass
class PartialParseResult:
    token_type: str   # "OPEN_QUOTE" | "EXPECT_ENTITY" | "EXPECT_KEYWORD" | "EXPECT_INT"
    partial: str      # partial text being typed at cursor
    token_start: int  # index in the original query where the current token starts (splice point)


_KEYWORD_RESTRICTION = {"some", "only", "value", "Self", "min", "max", "exactly"}
_KEYWORD_BOOLEAN = {"and", "or"}
_CURIE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*:[A-Za-z0-9_\-\.]+")
_FULL_IRI_RE = re.compile(r"<[^>]*>")
_INT_RE = re.compile(r"[0-9]+")


def _tokenize_prefix(text: str) -> list[tuple[str, str]]:
    """Tokenize completed text into (type, value) pairs. Skips open quotes."""
    tokens: list[tuple[str, str]] = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        if text[i] == "'":
            end = text.find("'", i + 1)
            if end == -1:
                break  # open quote — stop tokenising
            tokens.append(("QUOTED_LABEL", text[i:end + 1]))
            i = end + 1
            continue
        if text[i] == "<":
            end = text.find(">", i + 1)
            if end == -1:
                break
            tokens.append(("FULL_IRI", text[i:end + 1]))
            i = end + 1
            continue
        if text[i] == "(":
            tokens.append(("OPEN_PAREN", "("))
            i += 1
            continue
        if text[i] == ")":
            tokens.append(("CLOSE_PAREN", ")"))
            i += 1
            continue
        # Try keywords and identifiers
        rest = text[i:]
        word_m = re.match(r"[A-Za-z_][A-Za-z0-9_:\-\.]*", rest)
        if word_m:
            word = word_m.group(0)
            if word in _KEYWORD_RESTRICTION:
                tokens.append(("KW_RESTRICTION", word))
            elif word in _KEYWORD_BOOLEAN:
                tokens.append(("KW_BOOLEAN", word))
            elif word == "not":
                tokens.append(("KW_NOT", word))
            elif _CURIE_RE.fullmatch(word):
                tokens.append(("CURIE", word))
            else:
                tokens.append(("WORD", word))
            i += len(word)
            continue
        int_m = re.match(r"[0-9]+", rest)
        if int_m:
            tokens.append(("INT", int_m.group(0)))
            i += len(int_m.group(0))
            continue
        i += 1
    return tokens


def partial_parse(text: str, cursor: int) -> PartialParseResult:
    """Return the expected token type and partial text at cursor for autocomplete."""
    prefix = text[:cursor]

    # Detect open single quote
    in_quote = False
    quote_start = -1
    for idx, ch in enumerate(prefix):
        if ch == "'":
            if not in_quote:
                in_quote = True
                quote_start = idx
            else:
                in_quote = False
                quote_start = -1

    if in_quote:
        # Replace from char after the opening quote up to the cursor
        return PartialParseResult(
            token_type="OPEN_QUOTE",
            partial=prefix[quote_start + 1:],
            token_start=quote_start + 1,
        )

    tokens = _tokenize_prefix(prefix)

    if not tokens:
        return PartialParseResult(token_type="EXPECT_ENTITY", partial="", token_start=cursor)

    last_type, last_val = tokens[-1]

    # After a complete entity reference or closing paren → expect boolean keyword
    if last_type in ("QUOTED_LABEL", "CURIE", "FULL_IRI", "CLOSE_PAREN"):
        return PartialParseResult(token_type="EXPECT_KEYWORD", partial="", token_start=cursor)

    # After min/max/exactly → expect integer
    if last_type == "KW_RESTRICTION" and last_val in ("min", "max", "exactly"):
        return PartialParseResult(token_type="EXPECT_INT", partial="", token_start=cursor)

    # After integer → expect entity (filler class)
    if last_type == "INT":
        return PartialParseResult(token_type="EXPECT_ENTITY", partial="", token_start=cursor)

    # WORD token: if cursor is right after the word (no trailing space), the user is still
    # typing a bare label → surface entity completions for the partial text.
    if last_type == "WORD":
        if not prefix[-1:].isspace():
            token_start = cursor - len(last_val)
            return PartialParseResult(token_type="EXPECT_ENTITY", partial=last_val, token_start=token_start)
        # WORD followed by whitespace → completed bare entity, expect keyword next
        return PartialParseResult(token_type="EXPECT_KEYWORD", partial="", token_start=cursor)

    # After restriction keyword (some/only/value) or boolean (and/or) or not / ( → expect entity
    return PartialParseResult(token_type="EXPECT_ENTITY", partial="", token_start=cursor)
