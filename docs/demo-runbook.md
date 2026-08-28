# Demo-day runbook

The system runs on exactly one machine — the owner's M1 — and the moment that
matters is a live Consultation driven by the thesis advisor over LINE. Several
defaults are actively hostile to that moment and none of them are visible until
they fire in front of the advisor. This runbook is the launch ritual that
neutralizes them; `uv run python -m app.preflight` proves it worked, green/red,
before anyone touches the bot.

The numbers below (model load 14.5–23 s, vdb rebuild ~1–3 min, re-index ~2–4 min)
were measured on the target machine in ticket #24, which fixed the process shape:
**no `--reload`, one worker, pre-warmed at boot, embedding serialized.**

## The day before

Do everything that costs minutes or money today, so demo day is pure launch.

1. Check out the commit you will demo and sync:

   ```bash
   uv sync
   ```

2. **Confirm the KEYWORD model slot is configured.** LightRAG's `mix` query
   mode calls KEYWORD once per LINE message (ADR 0010); without an API key,
   a `mix` query silently degrades to `naive` -- grounded but flat, and
   nothing else in the pipeline surfaces the difference. Check `.env` for:

   ```
   KEYWORD_PROVIDER=
   KEYWORD_MODEL=
   KEYWORD_API_KEY=
   KEYWORD_BASE_URL=      # optional, provider-dependent
   ```

3. If GraphRAG is live (`rag_storage/` exists) and `vdb_*.json` is missing or
   stale, rebuild the derived vectors with this repo's own BGE-M3 wiring —
   the shipped `lightrag-rebuild-vdb` CLI cannot be pointed at local
   embeddings (its factory only builds hosted-provider bindings; see
   `.superpowers/sdd/phase-0-report.md`):

   ```bash
   uv run python scripts/rebuild_vdb.py
   ```

   ~1–3 min and $0. A re-index (adding or editing source notes) is a
   separate owner command, ~2–4 min plus LLM calls, and must be followed by
   `uv run python -m app.rag.source_notes corpus --write-manifest` so the
   staleness gate's manifest matches what was actually indexed. Both are
   strictly day-before work — never on demo day.

4. Start the stack and run the preflight; fix every red **today**:

   ```bash
   docker compose up -d
   ```

   ```bash
   uv run python -m app.preflight
   ```

   `graph-store`, `vdb-drift`, `corpus-books`, and `index-fresh` must all be
   green.

5. Run the full smoke turn (last section) over real LINE, including a tongue
   photo if the demo will show one.

## Demo day: the launch ritual

Four terminal panes, in this order.

1. **Keep the Mac awake.** A sleeping Mac kills the tunnel. Leave this running
   in its own pane for the whole session:

   ```bash
   caffeinate -dimsu
   ```

2. **MongoDB.** Every Health Record and Working Buffer write fails without it:

   ```bash
   docker compose up -d
   ```

3. **The named tunnel.** Never a quick tunnel: a quick tunnel's hostname
   changes on every restart, which silently orphans the webhook URL in the
   LINE console:

   ```bash
   cloudflared tunnel run ttm-demo
   ```

   One-time setup, long before demo day: `cloudflared tunnel login`, then
   `cloudflared tunnel create ttm-demo`, route a stable hostname to it with
   `cloudflared tunnel route dns ttm-demo <hostname>`, and point its ingress at
   `http://localhost:8000` in `~/.cloudflared/config.yml`. Set
   `PUBLIC_BASE_URL=https://<hostname>` in `.env` and set the LINE console's
   webhook URL to `https://<hostname>/webhook`. The preflight's `webhook` check
   verifies both ends match and runs LINE's own Verify.

4. **The server — reload-free, single worker, pre-warmed:**

   ```bash
   EMBEDDING_PREWARM=1 uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

   Expect ~15–23 s before "Application startup complete": that is BGE-M3
   loading *now* instead of on the advisor's first message. No `--reload`
   here, ever — LightRAG writes into its working directory at query time
   (the KEYWORD response lands in `kv_store_llm_response_cache.json`), so
   under `--reload` an incoming message can restart the server mid-Consultation.
   **Never add `--workers` here** — exactly one worker: each additional
   worker loads its own ~1 GB BGE-M3 and they would write the file-backed
   graph storage concurrently (`app/preflight.py`'s `server` check FAILs on
   more than one).

5. **Preflight:**

   ```bash
   uv run python -m app.preflight
   ```

   All green → run the smoke turn. Any red → the fix is printed under the
   check; re-run until green.

6. **The smoke turn** — the one check the preflight cannot run, because it
   cannot be the LINE user. From the owner's LINE account send:

   > ธาตุไฟกำเริบ ควรดูแลตัวเองอย่างไร

   The reply must arrive within seconds (the model is pre-warmed) and end with
   an `(อ้างอิง: …)` footer naming a real book section. If the demo includes
   tongue assessment, also send one tongue photo and confirm the echoed image
   comes back.

## The dev path (not demo day)

Day-to-day development keeps the reloader — with the exclude, which becomes
mandatory the moment `rag_storage/` exists, for the same
writes-at-query-time reason as above:

```bash
uv run uvicorn app.main:app --reload --reload-exclude 'rag_storage/*'
```

Leave `EMBEDDING_PREWARM` unset in dev: every reload would otherwise pay the
~15–23 s model load.

## Recovery

- **Tunnel drops mid-demo.** Restart pane 3 (`cloudflared tunnel run ttm-demo`).
  The hostname is stable, so the LINE console needs no change. Messages sent
  while it was down are gone — ask the advisor to resend the last message.
  Confirm recovery with the preflight's `tunnel` and `webhook` checks.

- **Server process dies mid-demo.** Relaunch pane 4 and wait for
  "Application startup complete" (~20 s of model load; `/health` reports
  `"embedding": "ready"`). Conversation state lives in MongoDB (Working
  Buffer + Health Records), not the process, so nothing is lost — resend the
  last message.

- **Mongo is down.** `docker compose up -d`. Health Record writes fail while
  it is down; the turn that hit the failure should be resent.

- **A reply feels slow.** Slow is not dropped: the webhook returns 200
  immediately and work happens in a background task; the loading animation
  covers 60 s and the reply degrades from reply to push after that (ADR 0007).
  Wait before touching anything.

- **Never on demo day:** vdb rebuild (~1–3 min), re-index/EXTRACT (~2–4 min
  plus LLM calls on the owner's plan), dependency updates, or model changes.
  All of that is day-before work by definition.
