"""Unit tests for app/preflight.py -- the pure and injectable check logic.

Network, process-table, and filesystem effects are injected (fake fetchers,
canned `ps` output, tmp_path), so these run anywhere: no server, tunnel,
Mongo, or LINE access needed. The two checks that stay I/O-bound end to end
(check_mongo, check_vdb_drift) are exercised for real on demo day; their
callers' branching is covered here.
"""

from app.config import Settings
from app.preflight import (
    AUTHORITATIVE_FILES,
    DERIVED_VDB_FILES,
    FAIL,
    PASS,
    WARN,
    CheckResult,
    check_caffeinate,
    check_corpus_books,
    check_env,
    check_graph_store,
    check_prewarm,
    check_server,
    check_tunnel,
    check_webhook,
    find_process,
    main,
    parse_check_index_output,
    render,
)

UVICORN = "  123 /repo/.venv/bin/python /repo/.venv/bin/uvicorn app.main:app --port 8000"
PS_CLEAN = UVICORN + "\n  456 caffeinate -dimsu\n  789 cloudflared tunnel run ttm-demo\n"


def _settings(**overrides) -> Settings:
    # Explicit values for every field the checks read: Settings has
    # env_file=".env" in model_config, so field defaults are not defaults
    # on a machine with a filled-in .env (commit a7785f7).
    values = {
        "line_channel_secret": "secret",
        "line_channel_access_token": "token",
        "advisor_api_key": "advisor-key",
        "describer_api_key": "describer-key",
        "public_base_url": "https://ttm.example.com",
    }
    values.update(overrides)
    return Settings(**values)


def _fetch(status_code: int, data: dict | None, err: str = ""):
    def fetch(url, headers=None):
        return status_code, data, err

    return fetch


# --- process checks ---------------------------------------------------------


def test_find_process_matches_all_needles():
    assert find_process(PS_CLEAN, "uvicorn", "app.main:app") is not None
    assert find_process(PS_CLEAN, "uvicorn", "other.app:app") is None


def test_server_passes_without_reload_single_worker():
    assert check_server(PS_CLEAN, 8000).status == PASS


def test_server_fails_when_not_running():
    result = check_server("  456 caffeinate -dimsu\n", 8000)
    assert result.status == FAIL
    assert "EMBEDDING_PREWARM=1" in result.hint


def test_server_fails_under_reload():
    result = check_server(UVICORN + " --reload\n", 8000)
    assert result.status == FAIL
    assert "--reload" in result.detail


def test_server_fails_with_multiple_workers():
    assert check_server(UVICORN + " --workers 4\n", 8000).status == FAIL
    assert check_server(UVICORN + " --workers=4\n", 8000).status == FAIL


def test_server_allows_explicit_single_worker():
    assert check_server(UVICORN + " --workers 1\n", 8000).status == PASS


def test_caffeinate_present_and_absent():
    assert check_caffeinate(PS_CLEAN).status == PASS
    assert check_caffeinate(UVICORN + "\n").status == FAIL


# --- env --------------------------------------------------------------------


def test_env_passes_with_all_credentials():
    assert check_env(_settings()).status == PASS


def test_env_fails_naming_empty_credentials():
    result = check_env(_settings(advisor_api_key="", describer_api_key=""))
    assert result.status == FAIL
    assert "ADVISOR_API_KEY" in result.detail
    assert "DESCRIBER_API_KEY" in result.detail


def test_env_warns_without_public_base_url():
    result = check_env(_settings(public_base_url=""))
    assert result.status == WARN


# --- tunnel -----------------------------------------------------------------


def test_tunnel_fails_without_cloudflared():
    assert check_tunnel(UVICORN + "\n", "https://ttm.example.com").status == FAIL


def test_tunnel_fails_on_quick_tunnel_hostname():
    result = check_tunnel(PS_CLEAN, "https://random-words.trycloudflare.com")
    assert result.status == FAIL
    assert "QUICK" in result.detail


def test_tunnel_passes_when_public_health_answers():
    fetch = _fetch(200, {"status": "ok", "embedding": "ready"})
    result = check_tunnel(PS_CLEAN, "https://ttm.example.com", fetch=fetch)
    assert result.status == PASS


def test_tunnel_fails_when_public_health_unreachable():
    fetch = _fetch(0, None, "connect timeout")
    result = check_tunnel(PS_CLEAN, "https://ttm.example.com", fetch=fetch)
    assert result.status == FAIL


# --- webhook ----------------------------------------------------------------


def _line_endpoint(endpoint: str, active: bool = True):
    return _fetch(200, {"endpoint": endpoint, "active": active})


def test_webhook_passes_when_url_matches_and_verify_succeeds():
    result = check_webhook(
        "https://ttm.example.com",
        "token",
        fetch=_line_endpoint("https://ttm.example.com/webhook"),
        post=_fetch(200, {"success": True}),
    )
    assert result.status == PASS


def test_webhook_tolerates_trailing_slash_differences():
    result = check_webhook(
        "https://ttm.example.com/",
        "token",
        fetch=_line_endpoint("https://ttm.example.com/webhook/"),
        post=_fetch(200, {"success": True}),
    )
    assert result.status == PASS


def test_webhook_fails_on_console_mismatch():
    result = check_webhook(
        "https://ttm.example.com",
        "token",
        fetch=_line_endpoint("https://old-host.example.com/webhook"),
        post=_fetch(200, {"success": True}),
    )
    assert result.status == FAIL
    assert "old-host.example.com" in result.detail


def test_webhook_fails_when_disabled_in_console():
    result = check_webhook(
        "https://ttm.example.com",
        "token",
        fetch=_line_endpoint("https://ttm.example.com/webhook", active=False),
        post=_fetch(200, {"success": True}),
    )
    assert result.status == FAIL


def test_webhook_fails_when_line_verify_fails():
    result = check_webhook(
        "https://ttm.example.com",
        "token",
        fetch=_line_endpoint("https://ttm.example.com/webhook"),
        post=_fetch(200, {"success": False, "reason": "COULD_NOT_CONNECT"}),
    )
    assert result.status == FAIL
    assert "COULD_NOT_CONNECT" in result.detail


# --- prewarm ----------------------------------------------------------------


def test_prewarm_passes_when_embedding_ready():
    result = check_prewarm(8000, fetch=_fetch(200, {"status": "ok", "embedding": "ready"}))
    assert result.status == PASS


def test_prewarm_fails_when_embedding_cold():
    result = check_prewarm(8000, fetch=_fetch(200, {"status": "ok", "embedding": "cold"}))
    assert result.status == FAIL
    assert "EMBEDDING_PREWARM=1" in result.hint


def test_prewarm_fails_on_old_build_without_field():
    result = check_prewarm(8000, fetch=_fetch(200, {"status": "ok"}))
    assert result.status == FAIL


def test_prewarm_fails_when_server_down():
    result = check_prewarm(8000, fetch=_fetch(0, None, "connection refused"))
    assert result.status == FAIL


# --- graph store -------------------------------------------------------------


def test_graph_store_fails_when_rag_storage_missing(tmp_path):
    # GraphRAG is live (ADR 0010): rag_storage/ is committed repo content, so
    # its absence is a real demo-killer now, not a pre-rollout WARN.
    result = check_graph_store(tmp_path)
    assert result.status == FAIL
    assert "rag_storage" in result.detail


def test_graph_store_fails_on_missing_authoritative_files(tmp_path):
    (tmp_path / "rag_storage").mkdir()
    result = check_graph_store(tmp_path)
    assert result.status == FAIL
    assert "authoritative" in result.detail


def test_graph_store_fails_on_missing_derived_vectors(tmp_path):
    storage = tmp_path / "rag_storage"
    storage.mkdir()
    for name in AUTHORITATIVE_FILES:
        (storage / name).write_text("{}")
    result = check_graph_store(tmp_path)
    assert result.status == FAIL
    assert "vdb_" in result.detail


def test_graph_store_passes_with_all_files(tmp_path):
    storage = tmp_path / "rag_storage"
    storage.mkdir()
    for name in AUTHORITATIVE_FILES + DERIVED_VDB_FILES:
        (storage / name).write_text("{}")
    assert check_graph_store(tmp_path).status == PASS


# --- corpus books -------------------------------------------------------


def test_corpus_books_passes_when_books_yaml_covers_every_folder(tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "four-elements").mkdir(parents=True)
    (corpus / "tongue-100").mkdir(parents=True)
    (corpus / "books.yaml").write_text(
        "four-elements: Title One\ntongue-100: Title Two\n", encoding="utf-8"
    )
    result = check_corpus_books(tmp_path)
    assert result.status == PASS
    assert "2" in result.detail


def test_corpus_books_fails_naming_uncovered_folders(tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "four-elements").mkdir(parents=True)
    (corpus / "tongue-100").mkdir(parents=True)
    (corpus / "books.yaml").write_text("four-elements: Title One\n", encoding="utf-8")
    result = check_corpus_books(tmp_path)
    assert result.status == FAIL
    assert "tongue-100" in result.detail


def test_corpus_books_fails_when_corpus_dir_missing(tmp_path):
    result = check_corpus_books(tmp_path)
    assert result.status == FAIL


def test_corpus_books_ignores_archive_directory(tmp_path):
    # corpus/archive/ (Phase 5, #14) holds retired TCM JSONLs, never a book
    # with a books.yaml entry -- it must not be flagged as an uncovered folder.
    corpus = tmp_path / "corpus"
    (corpus / "four-elements").mkdir(parents=True)
    (corpus / "tongue-100").mkdir(parents=True)
    (corpus / "archive").mkdir(parents=True)
    (corpus / "books.yaml").write_text(
        "four-elements: Title One\ntongue-100: Title Two\n", encoding="utf-8"
    )
    result = check_corpus_books(tmp_path)
    assert result.status == PASS
    assert "archive" not in result.detail


# --- index freshness --------------------------------------------------------


def test_check_index_not_implemented_is_a_warning():
    result = parse_check_index_output(2, "error: unrecognized arguments: --check-index")
    assert result.status == WARN


def test_check_index_fresh_passes():
    assert parse_check_index_output(0, "fresh").status == PASS


def test_check_index_stale_fails():
    result = parse_check_index_output(1, "stale: 2 changed, 1 new, 0 removed")
    assert result.status == FAIL
    assert "stale" in result.detail


# --- run_preflight composition ------------------------------------------------


def test_run_preflight_includes_corpus_books_when_graph_store_fails(monkeypatch):
    """When check_graph_store FAILs, check_corpus_books still runs (it does
    not depend on graph_store status) but check_vdb_drift is skipped (it is
    gated on graph_store passing). This pins the exact set of checks
    run_preflight composes (Phase 5, #14 retired the vector-store check that
    used to sit here)."""
    import app.preflight as preflight

    # Monkeypatch check_graph_store to return FAIL
    def fake_check_graph_store(repo_root):
        return CheckResult("graph-store", FAIL, "missing files")

    # Mock ps_snapshot to avoid process table reads
    monkeypatch.setattr(preflight, "ps_snapshot", lambda: PS_CLEAN)
    # Mock Settings instantiation
    monkeypatch.setattr(preflight, "Settings", lambda: _settings())

    # Patch individual checks to isolate just the composition
    monkeypatch.setattr(preflight, "check_graph_store", fake_check_graph_store)
    monkeypatch.setattr(
        preflight, "check_env", lambda settings: CheckResult("env", PASS, "ok")
    )
    monkeypatch.setattr(
        preflight, "check_mongo", lambda uri: CheckResult("mongo", PASS, "ok")
    )
    monkeypatch.setattr(
        preflight, "check_server", lambda ps, port: CheckResult("server", PASS, "ok")
    )
    monkeypatch.setattr(
        preflight, "check_prewarm", lambda port: CheckResult("prewarm", PASS, "ok")
    )
    monkeypatch.setattr(
        preflight, "check_caffeinate", lambda ps: CheckResult("caffeinate", PASS, "ok")
    )
    monkeypatch.setattr(
        preflight, "check_tunnel", lambda ps, url, fetch=None: CheckResult("tunnel", PASS, "ok")
    )
    monkeypatch.setattr(
        preflight,
        "check_webhook",
        lambda url, token, fetch=None: CheckResult("webhook", PASS, "ok"),
    )
    monkeypatch.setattr(
        preflight,
        "check_corpus_books",
        lambda repo_root: CheckResult("corpus-books", PASS, "ok"),
    )
    monkeypatch.setattr(
        preflight,
        "check_index_freshness",
        lambda repo_root: CheckResult("index-freshness", PASS, "fresh"),
    )

    results = preflight.run_preflight(8000)

    # Pin the exact composed check set: corpus-books always runs, vdb-drift
    # is skipped because graph-store failed, and no unexpected check appears.
    result_names = {r.name for r in results}
    result_statuses = {r.name: r.status for r in results}

    assert result_names == {
        "env",
        "mongo",
        "server",
        "prewarm",
        "caffeinate",
        "tunnel",
        "webhook",
        "graph-store",
        "corpus-books",
        "index-freshness",
    }
    assert result_statuses["graph-store"] == FAIL
    assert result_statuses["corpus-books"] == PASS


# --- rendering and exit code ------------------------------------------------


def test_render_includes_status_and_hint():
    results = [
        CheckResult("server", PASS, "single worker, no --reload"),
        CheckResult("mongo", FAIL, "ping failed", hint="docker compose up -d"),
    ]
    output = render(results, use_color=False)
    assert "PASS" in output and "FAIL" in output
    assert "fix: docker compose up -d" in output


def test_main_exit_code_reflects_failures(monkeypatch, capsys):
    import app.preflight as preflight

    monkeypatch.setattr(preflight, "run_preflight", lambda port: [CheckResult("x", FAIL, "boom")])
    assert main([]) == 1
    assert "NOT GO" in capsys.readouterr().out

    monkeypatch.setattr(preflight, "run_preflight", lambda port: [CheckResult("x", PASS, "ok")])
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "GO" in out
    assert "อ้างอิง" in out  # the manual smoke turn is always printed
