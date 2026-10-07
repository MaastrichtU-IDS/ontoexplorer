"""filter_already_classified returns only versions whose classification is cached
(reasoner-scoped or legacy bare key), via a single pipelined EXISTS — it must never
call the reasoner. Used by global expression search (#277) so one query can't
synchronously classify unreasoned ontologies."""
import pytest

from ontoexplorer.clients import reasoning


class _FakePipe:
    def __init__(self, keys):
        self.keys = keys
        self.cmds = []

    def exists(self, k):
        self.cmds.append(k)
        return self

    def execute(self):
        return [1 if k in self.keys else 0 for k in self.cmds]


class _FakeRedis:
    def __init__(self, keys):
        self.keys = set(keys)

    def pipeline(self, transaction=False):
        return _FakePipe(self.keys)


@pytest.mark.anyio
async def test_filter_already_classified(monkeypatch):
    monkeypatch.setattr(
        reasoning, "_elk_cache_redis",
        lambda: _FakeRedis({"classification:v1:rustdl", "classification:v2"}),
    )
    ready = await reasoning.filter_already_classified(
        [("v1", "rustdl"), ("v2", "rustdl"), ("v3", "rustdl")]
    )
    # v1 reasoner-scoped key, v2 legacy bare key, v3 absent
    assert ready == {"v1", "v2"}


@pytest.mark.anyio
async def test_filter_already_classified_empty():
    # Empty input short-circuits without touching Redis.
    assert await reasoning.filter_already_classified([]) == set()
