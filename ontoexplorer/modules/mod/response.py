import json

from fastapi import Response
from rdflib import Graph


HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{{ title }}</title>
<style>
body{font-family:sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#222}
h1{font-size:1.4rem;margin-bottom:1rem}
table{border-collapse:collapse;width:100%}
th,td{border:1px solid #ddd;padding:6px 10px;text-align:left;vertical-align:top;font-size:.85rem}
th{background:#f5f5f5;font-weight:600}
td:first-child{white-space:nowrap;color:#555}
a{color:#0066cc;text-decoration:none}
a:hover{text-decoration:underline}
</style>
</head>
<body>
<h1>{{ title }}</h1>
<table>
<thead><tr><th>Property</th><th>Value</th></tr></thead>
<tbody>
{% for pred, obj in rows %}
<tr>
  <td><a href="{{ pred }}">{{ pred_label(pred) }}</a></td>
  <td>{% if obj.startswith("http") %}<a href="{{ obj }}">{{ obj }}</a>{% else %}{{ obj }}{% endif %}</td>
</tr>
{% endfor %}
</tbody>
</table>
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


def _render_html(graph: Graph) -> str:
    from jinja2 import Environment
    env = Environment(autoescape=True)

    def pred_label(uri: str) -> str:
        if "#" in uri:
            return uri.split("#")[-1]
        return uri.rstrip("/").split("/")[-1]

    env.globals["pred_label"] = pred_label

    title_pred = "http://purl.org/dc/terms/title"
    title = next(
        (str(o) for _, p, o in graph if str(p) == title_pred),
        "RDF Graph",
    )
    rows = sorted((str(p), str(o)) for _, p, o in graph)
    tmpl = env.from_string(HTML_TEMPLATE)
    return tmpl.render(title=title, rows=rows)


def _serialize(graph: Graph, fmt: str) -> tuple[bytes, str]:
    if fmt == "turtle":
        return graph.serialize(format="turtle").encode("utf-8"), "text/turtle; charset=utf-8"
    if fmt == "xml":
        return graph.serialize(format="xml").encode("utf-8"), "application/rdf+xml; charset=utf-8"
    if fmt == "html":
        return _render_html(graph).encode("utf-8"), "text/html; charset=utf-8"
    # JSON-LD
    from ontoexplorer.modules.mod.context import MOD_CONTEXT
    raw = json.loads(graph.serialize(format="json-ld"))
    if isinstance(raw, list):
        data: dict = {"@context": MOD_CONTEXT["@context"], "@graph": raw}
    else:
        data = {"@context": MOD_CONTEXT["@context"], **raw}
    return json.dumps(data, indent=2).encode("utf-8"), "application/ld+json; charset=utf-8"


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
