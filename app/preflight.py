"""Demo-day preflight: green/red checks before anyone touches the bot.

Usage:
    uv run python -m app.preflight [--port 8000]

Every check is read-only -- this reports, it never fixes. The launch ritual
itself (and every fix for a red check) is docs/demo-runbook.md; ticket #24
measured why each of these defaults is a demo-killer.

GraphRAG is live (ADR 0010): the graph checks (``graph-store``,
``vdb-drift``, ``corpus-books``, ``index-fresh``) are authoritative, not
advisory -- a missing or stale graph is a FAIL.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from app.config import Settings

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

DEFAULT_PORT = 8000
HTTP_TIMEOUT_S = 10.0
MONGO_PING_TIMEOUT_MS = 3000

LAUNCH_CMD = "EMBEDDING_PREWARM=1 uv run uvicorn app.main:app --host 127.0.0.1 --port {port}"
LINE_WEBHOOK_API = "https://api.line.me/v2/bot/channel/webhook"

# Ticket #24: the authoritative half of rag_storage/ is committed repo
# content; the vdb_* half is derived, gitignored, and rebuilt in ~1-3 min
# with zero LLM calls. LightRAG 1.5.6 writes seven kv_store_*.json files
# beyond the graphml (#30) -- every one of them is authoritative and
# committed. Any filename change here must update ADR 0010's storage
# section too (ADR 0010, "Engine and storage").
AUTHORITATIVE_FILES = (
    "graph_chunk_entity_relation.graphml",
    "kv_store_doc_status.json",
    "kv_store_entity_chunks.json",
    "kv_store_full_docs.json",
    "kv_store_full_entities.json",
    "kv_store_full_relations.json",
    "kv_store_relation_chunks.json",
    "kv_store_text_chunks.json",
)
DERIVED_VDB_FILES = ("vdb_entities.json", "vdb_relationships.json", "vdb_chunks.json")

SMOKE_TURN = """\
Final check -- one real smoke turn, by hand (preflight cannot be the LINE user):
  1. From the owner's LINE account send:  ธาตุไฟกำเริบ ควรดูแลตัวเองอย่างไร
  2. The reply must arrive within seconds (pre-warmed) and end with an
     (อ้างอิง: ...) footer naming a real book section.
All-green preflight but a failed smoke turn means the pipeline, not the
plumbing -- see docs/demo-runbook.md, Recovery."""


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # PASS | WARN | FAIL
    detail: str
    hint: str = ""


# (status_code, parsed_json, error) -- status_code 0 means the request never
# completed and error carries the reason.
FetchJson = Callable[..., tuple[int, dict | None, str]]


def _get_json(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict | None, str]:
    try:
        resp = httpx.get(url, headers=headers, timeout=HTTP_TIMEOUT_S)
    except httpx.HTTPError as exc:
        return 0, None, str(exc)
    try:
        return resp.status_code, resp.json(), ""
    except ValueError:
        return resp.status_code, None, resp.text[:200]


def _post_json(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict | None, str]:
    try:
        resp = httpx.post(url, headers=headers, json={}, timeout=HTTP_TIMEOUT_S)
    except httpx.HTTPError as exc:
        return 0, None, str(exc)
    try:
        return resp.status_code, resp.json(), ""
    except ValueError:
        return resp.status_code, None, resp.text[:200]


def ps_snapshot() -> str:
    return subprocess.run(
        ["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=False
    ).stdout


def find_process(ps: str, *needles: str) -> str | None:
    for line in ps.splitlines():
        if all(needle in line for needle in needles):
            return line.strip()
    return None


def _flag_value(cmdline: str, flag: str) -> str | None:
    tokens = cmdline.split()
    for i, token in enumerate(tokens):
        if token == flag and i + 1 < len(tokens):
            return tokens[i + 1]
        if token.startswith(flag + "="):
            return token.split("=", 1)[1]
    return None


def check_env(settings: Settings) -> CheckResult:
    credentials = (
        ("LINE_CHANNEL_SECRET", settings.line_channel_secret),
        ("LINE_CHANNEL_ACCESS_TOKEN", settings.line_channel_access_token),
        ("ADVISOR_API_KEY", settings.advisor_api_key),
        ("DESCRIBER_API_KEY", settings.describer_api_key),
    )
    empty = [name for name, value in credentials if not value]
    if empty:
        return CheckResult("env", FAIL, "empty: " + ", ".join(empty), hint="fill them in .env")
    if not settings.public_base_url:
        return CheckResult(
            "env",
            WARN,
            "PUBLIC_BASE_URL empty -- tongue-photo echo is disabled (ADR 0007)",
            hint="set it to the named tunnel origin",
        )
    return CheckResult("env", PASS, "credentials present, PUBLIC_BASE_URL set")


def check_server(ps: str, port: int) -> CheckResult:
    cmdline = find_process(ps, "uvicorn", "app.main:app")
    if cmdline is None:
        return CheckResult(
            "server",
            FAIL,
            "no `uvicorn app.main:app` process",
            hint=LAUNCH_CMD.format(port=port),
        )
    if "--reload" in cmdline:
        return CheckResult(
            "server",
            FAIL,
            "running WITH --reload: LightRAG writes to its working dir at query time, so an"
            " incoming message can restart the server (~15 s model reload each time)",
            hint="relaunch: " + LAUNCH_CMD.format(port=port),
        )
    workers = _flag_value(cmdline, "--workers")
    if workers is not None and workers.isdigit() and int(workers) > 1:
        return CheckResult(
            "server",
            FAIL,
            f"{workers} workers: each loads its own ~1 GB BGE-M3 and they write the"
            " file-backed graph storage concurrently",
            hint="one worker only",
        )
    return CheckResult("server", PASS, "single worker, no --reload")


def check_prewarm(port: int, fetch: FetchJson = _get_json) -> CheckResult:
    status, data, err = fetch(f"http://127.0.0.1:{port}/health")
    if status != 200 or data is None:
        return CheckResult(
            "prewarm",
            FAIL,
            f"local /health -> {status or err}",
            hint=f"is the server running on port {port}?",
        )
    embedding = data.get("embedding")
    if embedding is None:
        return CheckResult(
            "prewarm",
            FAIL,
            "/health reports no embedding state -- an old build is running",
            hint="restart the server from the current checkout",
        )
    if embedding != "ready":
        return CheckResult(
            "prewarm",
            FAIL,
            "embedding cold: the demo's first message would wait 14.5-23 s on the model load",
            hint="relaunch with EMBEDDING_PREWARM=1",
        )
    return CheckResult("prewarm", PASS, "BGE-M3 resident before the first request")


def check_caffeinate(ps: str) -> CheckResult:
    if find_process(ps, "caffeinate") is None:
        return CheckResult(
            "caffeinate",
            FAIL,
            "not running -- a sleeping Mac kills the tunnel",
            hint="run `caffeinate -dimsu` in its own terminal for the whole session",
        )
    return CheckResult("caffeinate", PASS, "running")


def check_tunnel(ps: str, public_base_url: str, fetch: FetchJson = _get_json) -> CheckResult:
    if find_process(ps, "cloudflared") is None:
        return CheckResult(
            "tunnel", FAIL, "no cloudflared process", hint="cloudflared tunnel run <tunnel-name>"
        )
    if not public_base_url:
        return CheckResult(
            "tunnel",
            FAIL,
            "PUBLIC_BASE_URL empty -- cannot probe the public origin",
            hint="set PUBLIC_BASE_URL to the named tunnel origin",
        )
    host = urlparse(public_base_url).hostname or ""
    if host.endswith("trycloudflare.com"):
        return CheckResult(
            "tunnel",
            FAIL,
            f"{host} is a QUICK tunnel: its hostname changes every restart and silently"
            " orphans the webhook URL in the LINE console",
            hint="create a named tunnel with a stable hostname (docs/demo-runbook.md)",
        )
    status, data, err = fetch(public_base_url.rstrip("/") + "/health")
    if status != 200 or data is None or data.get("status") != "ok":
        return CheckResult(
            "tunnel",
            FAIL,
            f"GET {host}/health -> {status or err}",
            hint="tunnel up but app unreachable: does the ingress port match the server port?",
        )
    return CheckResult("tunnel", PASS, f"named tunnel serving at {host}")


def check_webhook(
    public_base_url: str,
    channel_access_token: str,
    fetch: FetchJson = _get_json,
    post: FetchJson = _post_json,
) -> CheckResult:
    if not public_base_url:
        return CheckResult(
            "webhook", FAIL, "PUBLIC_BASE_URL empty -- cannot compare with the LINE console"
        )
    headers = {"Authorization": f"Bearer {channel_access_token}"}
    expected = public_base_url.rstrip("/") + "/webhook"
    status, data, err = fetch(LINE_WEBHOOK_API + "/endpoint", headers)
    if status != 200 or data is None:
        return CheckResult(
            "webhook",
            FAIL,
            f"LINE endpoint API -> {status or err}",
            hint="channel access token wrong, or LINE API unreachable",
        )
    actual = str(data.get("endpoint", ""))
    if actual.rstrip("/") != expected:
        return CheckResult(
            "webhook",
            FAIL,
            f"LINE console points at {actual or '(unset)'} but this machine serves {expected}",
            hint="update the webhook URL in the LINE Developers Console",
        )
    if not data.get("active", False):
        return CheckResult(
            "webhook",
            FAIL,
            "webhook delivery is disabled in the LINE console",
            hint='enable "Use webhook" in the LINE Developers Console',
        )
    status, data, err = post(LINE_WEBHOOK_API + "/test", headers)
    if status != 200 or data is None or not data.get("success", False):
        reason = (data or {}).get("reason") or (data or {}).get("detail") or err or status
        return CheckResult("webhook", FAIL, f"LINE Verify failed: {reason}")
    return CheckResult("webhook", PASS, "console URL matches and LINE Verify passes")


def check_mongo(uri: str) -> CheckResult:
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError

    try:
        MongoClient(uri, serverSelectionTimeoutMS=MONGO_PING_TIMEOUT_MS).admin.command("ping")
    except PyMongoError as exc:
        return CheckResult(
            "mongo",
            FAIL,
            f"ping failed: {exc}",
            hint="docker compose up -d   (every Health Record write fails without it)",
        )
    return CheckResult("mongo", PASS, "ping ok -- Health Record writes will land")


def check_graph_store(repo_root: Path) -> CheckResult:
    storage = repo_root / "rag_storage"
    if not storage.is_dir():
        return CheckResult(
            "graph-store",
            FAIL,
            "rag_storage/ missing -- GraphRAG is live (ADR 0010), so the graph is expected"
            " committed repo content, not an optional extra",
            hint="git checkout rag_storage/ from the commit you are demoing, never re-extract"
            " on demo day",
        )
    missing = [name for name in AUTHORITATIVE_FILES if not (storage / name).exists()]
    if missing:
        return CheckResult(
            "graph-store",
            FAIL,
            "authoritative files missing: " + ", ".join(missing),
            hint="these are committed repo content (#24): restore from git, never re-extract"
            " on demo day",
        )
    missing = [name for name in DERIVED_VDB_FILES if not (storage / name).exists()]
    if missing:
        return CheckResult(
            "graph-store",
            FAIL,
            "derived vectors missing: " + ", ".join(missing),
            hint="vdb rebuild is ~1-3 min, $0 (docs/demo-runbook.md) -- do it TODAY, never"
            " on demo day",
        )
    return CheckResult("graph-store", PASS, "authoritative + derived files all present")


ARCHIVE_DIR_NAME = "archive"


def check_corpus_books(repo_root: Path) -> CheckResult:
    """corpus/books.yaml must name every corpus/<book_id>/ folder (ADR 0010):
    an uncovered folder is a book whose notes would validate its own
    book_id field yet still fail citation rendering, which reads titles
    from books.yaml alone. corpus/archive/ (Phase 5, #14) is excluded: it
    holds retired JSONLs that are never ingested and never a book_id."""
    from app.rag.source_notes import load_books

    corpus_root = repo_root / "corpus"
    if not corpus_root.is_dir():
        return CheckResult("corpus-books", FAIL, "corpus/ directory missing")
    books = load_books(corpus_root)
    book_dirs = sorted(
        p.name for p in corpus_root.iterdir() if p.is_dir() and p.name != ARCHIVE_DIR_NAME
    )
    missing = [name for name in book_dirs if name not in books]
    if missing:
        return CheckResult(
            "corpus-books",
            FAIL,
            "corpus/books.yaml missing entries for: " + ", ".join(missing),
            hint="add book_id: title to corpus/books.yaml",
        )
    return CheckResult(
        "corpus-books", PASS, f"books.yaml covers all {len(book_dirs)} corpus folder(s)"
    )


async def _vdb_consistency_report(storage: Path) -> dict:
    """Mirror lightrag's own RebuildTool check-only mode: file-backed defaults
    (#10), stub embedding func -- check_vdb_consistency reads ids, never embeds."""
    from lightrag.kg.factory import get_storage_class
    from lightrag.kg.shared_storage import initialize_share_data
    from lightrag.namespace import NameSpace
    from lightrag.tools.rebuild_vdb import check_vdb_consistency
    from lightrag.utils import EmbeddingFunc

    async def _no_embedding(*_args, **_kwargs):
        raise RuntimeError("preflight is read-only and must never embed")

    embedding_func = EmbeddingFunc(embedding_dim=1024, func=_no_embedding)
    global_config = {
        "working_dir": str(storage),
        "kv_storage": "JsonKVStorage",
        "vector_storage": "NanoVectorDBStorage",
        "graph_storage": "NetworkXStorage",
        "embedding_batch_num": 10,
        "vector_db_storage_cls_kwargs": {"cosine_better_than_threshold": 0.2},
        "embedding_func": embedding_func,
    }
    initialize_share_data(workers=1)
    graph = get_storage_class("NetworkXStorage")(
        namespace=NameSpace.GRAPH_STORE_CHUNK_ENTITY_RELATION,
        workspace="",
        global_config=global_config,
        embedding_func=embedding_func,
    )
    entities = get_storage_class("NanoVectorDBStorage")(
        namespace=NameSpace.VECTOR_STORE_ENTITIES,
        workspace="",
        global_config=global_config,
        embedding_func=embedding_func,
        meta_fields={"entity_name", "source_id", "content", "file_path"},
    )
    relationships = get_storage_class("NanoVectorDBStorage")(
        namespace=NameSpace.VECTOR_STORE_RELATIONSHIPS,
        workspace="",
        global_config=global_config,
        embedding_func=embedding_func,
        meta_fields={"src_id", "tgt_id", "source_id", "content", "file_path"},
    )
    for store in (graph, entities, relationships):
        await store.initialize()
    return await check_vdb_consistency(graph, entities, relationships)


def check_vdb_drift(repo_root: Path) -> CheckResult:
    try:
        report = asyncio.run(_vdb_consistency_report(repo_root / "rag_storage"))
    except ImportError:
        return CheckResult(
            "vdb-drift",
            WARN,
            "lightrag-hku not importable",
            hint="uv sync   (lightrag-hku is a core dependency as of #24's rollout;"
            " check pyproject.toml/uv.lock)",
        )
    except Exception as exc:  # storage init can fail in many library-internal ways
        return CheckResult("vdb-drift", FAIL, f"consistency check crashed: {exc}")
    missing = report["missing_entities"] + report["missing_relations"]
    detail = (
        f"graph has {report['graph_entities']} entities / {report['graph_relations']}"
        f" relations; missing from vectors: {report['missing_entities']} /"
        f" {report['missing_relations']}"
    )
    if missing:
        return CheckResult(
            "vdb-drift",
            FAIL,
            detail,
            hint="vdb rebuild (~1-3 min, $0) TODAY, never on demo day -- docs/demo-runbook.md",
        )
    return CheckResult("vdb-drift", PASS, detail)


def parse_check_index_output(returncode: int, output: str) -> CheckResult:
    if "unrecognized arguments" in output:
        return CheckResult(
            "index-fresh",
            WARN,
            "--check-index not recognized by app.rag.source_notes -- version skew?",
            hint="uv sync and confirm this checkout has the ticket #24 staleness gate",
        )
    if returncode == 0 and "fresh" in output:
        return CheckResult("index-fresh", PASS, "index matches corpus")
    first_line = output.splitlines()[0] if output else f"exit {returncode}"
    return CheckResult(
        "index-fresh",
        FAIL,
        first_line,
        hint="re-index is an owner command (~2-4 min + LLM calls) -- do it TODAY, never"
        " on demo day",
    )


def check_index_freshness(repo_root: Path) -> CheckResult:
    if not (repo_root / "rag_storage").is_dir():
        return CheckResult("index-fresh", WARN, "skipped -- no graph index yet")
    proc = subprocess.run(
        [sys.executable, "-m", "app.rag.source_notes", "corpus", "--check-index"],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
    )
    return parse_check_index_output(proc.returncode, (proc.stdout + proc.stderr).strip())


def run_preflight(port: int) -> list[CheckResult]:
    repo_root = Path(__file__).resolve().parent.parent
    ps = ps_snapshot()
    try:
        settings = Settings()
    except ValidationError as exc:
        fields = ", ".join(str(err["loc"][0]) for err in exc.errors())
        return [
            CheckResult(
                "env",
                FAIL,
                f"settings failed to load (missing: {fields})",
                hint="cp .env.example .env and fill it in",
            ),
            check_server(ps, port),
            check_caffeinate(ps),
        ]

    results = [
        check_env(settings),
        check_mongo(settings.mongodb_uri),
        check_server(ps, port),
        check_prewarm(port),
        check_caffeinate(ps),
        check_tunnel(ps, settings.public_base_url),
        check_webhook(settings.public_base_url, settings.line_channel_access_token),
    ]
    graph_store = check_graph_store(repo_root)
    results.append(graph_store)
    if graph_store.status == PASS:
        results.append(check_vdb_drift(repo_root))
    results.append(check_corpus_books(repo_root))
    results.append(check_index_freshness(repo_root))
    return results


_COLORS = {PASS: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m"}
_ICONS = {PASS: "✅", WARN: "⚠️ ", FAIL: "❌"}


def render(results: list[CheckResult], use_color: bool) -> str:
    width = max(len(result.name) for result in results)
    lines = []
    for result in results:
        color = _COLORS[result.status] if use_color else ""
        reset = "\033[0m" if use_color else ""
        lines.append(
            f"{_ICONS[result.status]} {color}{result.status}{reset}"
            f"  {result.name.ljust(width)}  {result.detail}"
        )
        if result.hint:
            lines.append(f"{' ' * (width + 10)}fix: {result.hint}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.preflight",
        description="Demo-day preflight: report green/red on every runtime dependency.",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="local server port (default: 8000)"
    )
    args = parser.parse_args(argv)
    results = run_preflight(args.port)
    print(render(results, use_color=sys.stdout.isatty()))
    print()
    print(SMOKE_TURN)
    if any(result.status == FAIL for result in results):
        print("\nNOT GO -- fix the FAIL items above, then re-run.")
        return 1
    print("\nGO -- all automated checks pass. Run the smoke turn.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
