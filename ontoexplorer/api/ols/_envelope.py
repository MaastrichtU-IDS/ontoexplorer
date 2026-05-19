"""Response envelope builders for OLS-compat layer."""
from math import ceil
from typing import Any
from fastapi import Request


def _total_pages(total: int, size: int) -> int:
    if total <= 0 or size <= 0:
        return 0
    return ceil(total / size)


def _build_page_links(request: Request, total: int, page: int, size: int) -> dict[str, dict[str, str]]:
    base = str(request.url).split("?")[0]
    # Preserve existing query params except page/size
    params = {k: v for k, v in request.query_params.items() if k not in ("page", "size")}

    def _url(p: int) -> str:
        merged = {**params, "page": str(p), "size": str(size)}
        return f"{base}?" + "&".join(f"{k}={v}" for k, v in merged.items())

    total_pages = _total_pages(total, size)
    links: dict[str, dict[str, str]] = {
        "self":  {"href": _url(page)},
        "first": {"href": _url(0)},
    }
    if total_pages > 0:
        links["last"] = {"href": _url(total_pages - 1)}
    if page > 0:
        links["prev"] = {"href": _url(page - 1)}
    if page < total_pages - 1:
        links["next"] = {"href": _url(page + 1)}
    return links


def hal_page(
    items: list[Any],
    request: Request,
    *,
    total: int,
    page: int,
    size: int,
    embedded_key: str,
) -> dict[str, Any]:
    return {
        "_embedded": {embedded_key: items},
        "_links": _build_page_links(request, total, page, size),
        "page": {"size": size, "totalElements": total, "totalPages": _total_pages(total, size), "number": page},
    }


def v2_page(
    items: list[Any],
    request: Request,
    *,
    total: int,
    page: int,
    size: int,
    facets: dict[str, list] | None = None,
) -> dict[str, Any]:
    return {
        "elements": items,
        "page": {"size": size, "totalElements": total, "totalPages": _total_pages(total, size), "number": page},
        "facetFieldsToCounts": facets or {},
    }
