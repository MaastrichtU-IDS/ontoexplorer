"""A class page must not return an unbounded hierarchy.

Asking for DRON's `BFO_0000001` (its `entity` root) produced a 73 MB response:
the asserted-subclasses query had no LIMIT and the inferred lists were whole
transitive closures. No UI can use 771k entries, and serialising them dominated
the request.

Lists are capped and reported alongside a total, so the page can say
"200 of 771,512" and send the reader to the tree.
"""

from ontoexplorer.api.ontologies import TERM_RELATION_LIMIT, bound_relation


def test_short_lists_pass_through_untouched():
    items = ["a", "b", "c"]
    assert bound_relation(items) == (items, 3, False)


def test_empty_list():
    assert bound_relation([]) == ([], 0, False)


def test_long_lists_are_capped_and_report_the_true_total():
    items = [f"c{i}" for i in range(TERM_RELATION_LIMIT + 500)]
    got, total, truncated = bound_relation(items)
    assert len(got) == TERM_RELATION_LIMIT
    assert got == items[:TERM_RELATION_LIMIT]
    assert total == TERM_RELATION_LIMIT + 500
    assert truncated is True


def test_exactly_at_the_cap_is_not_truncated():
    items = [f"c{i}" for i in range(TERM_RELATION_LIMIT)]
    got, total, truncated = bound_relation(items)
    assert len(got) == TERM_RELATION_LIMIT and total == TERM_RELATION_LIMIT
    assert truncated is False


def test_the_cap_matches_the_trees_page_size():
    """200 keeps a class page consistent with one page of the navigation tree."""
    assert TERM_RELATION_LIMIT == 200
