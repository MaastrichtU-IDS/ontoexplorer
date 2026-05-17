import json
from collections import defaultdict

from fastapi import Response
from rdflib import Graph


HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{{ title }}</title>
<style>
body{font-family:sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#222}
h1{font-size:1.5rem;margin-bottom:1.5rem}
h2{font-size:1rem;font-weight:600;margin:1.5rem 0 .4rem;padding:.3rem .5rem;background:#f0f4f8;border-left:3px solid #0066cc}
h2 a{color:#003d7a;text-decoration:none}
h2 a:hover{text-decoration:underline}
table{border-collapse:collapse;width:100%;margin-bottom:.5rem}
th,td{border:1px solid #ddd;padding:5px 10px;text-align:left;vertical-align:top;font-size:.82rem}
th{background:#f5f5f5;font-weight:600;width:220px}
a{color:#0066cc;text-decoration:none}
a:hover{text-decoration:underline}
</style>
</head>
<body>
<h1>{{ title }}</h1>
{% for subject, rows in groups %}
<h2>{% if subject.startswith("http") %}<a href="{{ subject }}">{{ subject_label(subject) }}</a>{% else %}{{ subject }}{% endif %}</h2>
<table>
<tbody>
{% for pred, obj in rows %}
<tr>
  <th><a href="{{ pred }}">{{ pred_label(pred) }}</a></th>
  <td>{% if obj.startswith("http") %}<a href="{{ obj }}">{{ obj }}</a>{% else %}{{ obj }}{% endif %}</td>
</tr>
{% endfor %}
</tbody>
</table>
{% endfor %}
</body>
</html>"""


def _negotiate_format(fmt_param: str | None, accept: str | None) -> str:
    FORMAT_MAP = {"jsonld": "jsonld", "ttl": "turtle", "rdfxml": "xml", "html": "html"}
    if fmt_param and fmt_param in FORMAT_MAP:
        return FORMAT_MAP[fmt_param]
    if accept:
        if "text/turtle" in accept:
            return "turtle"
        if "application/rdf+xml" in accept:
            return "xml"
        if "text/html" in accept:
            return "html"
    return "jsonld"


def _short_label(uri: str) -> str:
    if "#" in uri:
        return uri.split("#")[-1]
    return uri.rstrip("/").split("/")[-1]


def _render_html(graph: Graph) -> str:
    from jinja2 import Environment
    env = Environment(autoescape=True)
    env.globals["pred_label"] = _short_label

    title_pred = "http://purl.org/dc/terms/title"
    acronym_pred = "https://w3id.org/mod#acronym"
    collection_type = "http://www.w3.org/ns/hydra/core#Collection"
    rdf_type_pred = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

    # Group triples by subject
    by_subject: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for s, p, o in graph:
        by_subject[str(s)].append((str(p), str(o)))
    for rows in by_subject.values():
        rows.sort()

    # Build per-subject label: prefer mod:acronym, then dcterms:title, then IRI fragment
    def _subject_label(subj: str) -> str:
        rows = by_subject.get(subj, [])
        acronym = next((o for p, o in rows if p == acronym_pred), None)
        if acronym:
            return acronym
        t = next((o for p, o in rows if p == title_pred), None)
        if t:
            return t
        return _short_label(subj)

    env.globals["subject_label"] = _subject_label

    # Page title: use dcterms:title on the collection subject if present,
    # otherwise derive from the collection URI path, otherwise first title found
    collection_subj = next(
        (s for s, rows in by_subject.items()
         if any(p == rdf_type_pred and o == collection_type for p, o in rows)),
        None,
    )
    if collection_subj:
        title = next(
            (o for p, o in by_subject[collection_subj] if p == title_pred),
            _short_label(collection_subj).replace("-", " ").replace("_", " ").title(),
        )
    else:
        title = next(
            (str(o) for _, p, o in graph if str(p) == title_pred),
            "RDF Graph",
        )

    # Put the collection subject first, then artefacts (those with acronym/title), then the rest
    def _sort_key(item: tuple[str, list]) -> tuple[int, str]:
        subj, rows = item
        if subj == collection_subj:
            return (0, subj)
        has_acronym = any(p == acronym_pred for p, _ in rows)
        has_title = any(p == title_pred for p, _ in rows)
        return (1 if (has_acronym or has_title) else 2, _subject_label(subj))

    groups = sorted(by_subject.items(), key=_sort_key)

    tmpl = env.from_string(HTML_TEMPLATE)
    return tmpl.render(title=title, groups=groups)


def _serialize(graph: Graph, fmt: str) -> tuple[bytes, str]:
    if fmt == "turtle":
        return graph.serialize(format="turtle").encode("utf-8"), "text/turtle; charset=utf-8"
    if fmt == "xml":
        return graph.serialize(format="xml").encode("utf-8"), "application/rdf+xml; charset=utf-8"
    if fmt == "html":
        return _render_html(graph).encode("utf-8"), "text/html; charset=utf-8"
    # JSON-LD — pass context to rdflib so it compacts prefixes
    from ontoexplorer.modules.mod.context import MOD_CONTEXT
    raw = json.loads(graph.serialize(format="json-ld", context=MOD_CONTEXT["@context"]))
    return json.dumps(raw, indent=2).encode("utf-8"), "application/ld+json; charset=utf-8"


class RDFResponse(Response):
    def __init__(
        self,
        graph: Graph,
        *,
        format_param: str | None = None,
        accept: str | None = None,
    ) -> None:
        fmt = _negotiate_format(format_param, accept)
        content, media_type = _serialize(graph, fmt)
        super().__init__(content=content, media_type=media_type)
