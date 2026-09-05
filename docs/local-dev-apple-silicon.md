# Local development on Apple Silicon (arm64)

The tracked stack targets **linux/amd64** — the architecture of CI and the
production server. On an Apple Silicon Mac that runs under emulation, and the
cffi-based **py-whelk** (the default reasoner) segfaults when emulated. This
page describes the opt-in arm64 overlay that makes the reasoner-service build
natively so all four reasoners work locally.

**Nothing here affects the x64 server.** The server builds and runs
`docker-compose.yml` + `docker/reasoner-service/Dockerfile` alone (native
amd64, native Konclude, PyPI py-horned-owl/whelk wheels). The arm64 pieces are
only ever pulled in by an explicit `-f docker-compose.arm64.yml` (or the
`COMPOSE_FILE` chain below), which the server never sets.

## What the overlay does

| File | Tracked? | Role |
|------|----------|------|
| `docker-compose.yml` | yes | Canonical amd64 stack (prod/CI/server). Untouched. |
| `docker/reasoner-service/Dockerfile` | yes | Canonical amd64 reasoner image. Untouched. |
| `docker-compose.arm64.yml` | yes | Opt-in overlay: reasoner-service → `Dockerfile.arm64` (native arm64); app services pinned amd64 (emulated). |
| `docker/reasoner-service/Dockerfile.arm64` | yes | Native arm64 reasoner build. |
| `docker/reasoner-service/wheels-arm64/` | yes | aarch64 py-whelk wheel + build patch (kept out of `wheels/` so the amd64 Dockerfile stays byte-identical). |
| `docker-compose.override.yml` | no (gitignored) | This machine's quirks only: host-port remaps, single-RocksDB-writer worker layout, monitoring off. |
| `.env` | no (gitignored) | Local config, incl. the `COMPOSE_FILE` chain below. |

### Reasoner coverage in the arm64 image

- **rustdl** — PyPI aarch64 wheel. The default reasoner, and the justifier for
  every reasoner. Version is pinned in `docker/reasoner-service/Dockerfile.arm64`.
- **km** — kobayashi-marust, compiled from source for aarch64.
- **konclude** — no arm64 build exists anywhere; bundled as the x86_64 binary
  plus a small sysroot and run under `qemu-user`. It's a batch subprocess, so
  per-call emulation is fine; rustdl and km stay native.

whelk and the legacy rdflib classifier were removed and are no longer
registered — `docker/reasoner-service/registry.py` is the source of truth for
what is selectable.

## Setup on a new Apple Silicon machine

Add this line to your (gitignored) `.env` so a plain `docker compose ...`
chains the base file, the arm64 overlay, and your local override:

```
COMPOSE_FILE=docker-compose.yml:docker-compose.arm64.yml:docker-compose.override.yml
```

> Setting `COMPOSE_FILE` disables Compose's automatic loading of
> `docker-compose.override.yml`, so it must appear in the list explicitly.

Then:

```bash
docker compose build reasoner-service   # native arm64 (compiles py-horned-owl once)
docker compose up -d
```

Without the `.env` line, invoke the overlay explicitly:

```bash
docker compose -f docker-compose.yml -f docker-compose.arm64.yml \
               -f docker-compose.override.yml up -d
```

Verify all four reasoners are live:

```bash
curl -s http://localhost:8010/api/v1/reasoners   # api is on 8010 via the override
```

## The x64 server / CI

Do nothing special. No `COMPOSE_FILE` line in the server's `.env`, no
`-f docker-compose.arm64.yml`. `docker compose up -d` builds the amd64 images
from `docker-compose.yml` + `Dockerfile` (native Konclude, no qemu). The arm64
files sit inert in the repo.

## Rebuilding the aarch64 py-whelk wheel

The vendored wheel in `wheels-arm64/` was built from py-whelk source with
`wheels-arm64/py-whelk-arm64.patch` applied (adds remove-handling to the
`index_remove` stub so `reasoner.flush()` invalidates the cached classification
after `onto.remove_axiom()` — required by the persistent-reasoner justify path).
Rebuild it only when bumping py-whelk: apply the patch to the matching source
tag and `maturin build --release` on an arm64 host, then drop the resulting
`py_whelk-*aarch64.whl` into `wheels-arm64/`. Retire both once the upstream PR
lands and PyPI ships an aarch64 wheel.
