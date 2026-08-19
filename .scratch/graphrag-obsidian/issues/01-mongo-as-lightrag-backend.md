# 01 — Can local MongoDB actually back LightRAG?

Status: closed
Type: wayfinder:research
Map: ../MAP.md
Blocked by: none

## Question

LightRAG lists MongoDB as a unified storage backend (graph + vectors + KV). We run
Mongo locally via `docker-compose.yml`. But Mongo's vector search has historically
been an **Atlas-only** feature (`$vectorSearch` / Atlas Search), not available in
the community server.

So: does LightRAG's MongoDB backend work against a **local, non-Atlas** Mongo, or
does it silently require Atlas?

Answer must cover:

- Which LightRAG storage classes are Mongo-backed, and which of graph / vector / KV
  each covers.
- Whether the vector half requires Atlas `$vectorSearch`, and if so what the minimum
  Atlas tier costs.
- What LightRAG does if the index is missing — hard error, or slow brute-force scan?
  (At ~200 chunks a brute-force scan may be perfectly fine, which would make this a
  non-issue.)
- The fallback ranking if Atlas is required: Neo4j, Memgraph, or LightRAG's default
  file storage (NetworkX + nano-vectordb).

## Why it matters

The whole storage decision rests on this, and it was chosen *because* it added no
new services. If Mongo can't serve vectors locally, the "zero new infrastructure"
argument collapses and the choice should be revisited before ticket 07 builds on it.

## Resolution (2026-08-19)

**No. Local community MongoDB cannot back LightRAG's vector store.**

From LightRAG's `env.example`, verbatim:

> "For MongoVectorDBStorage, MONGO_URI must point to a MongoDB endpoint with
> Atlas Search / Vector Search support, such as MongoDB Atlas or Atlas local."

`docker-compose.yml` runs plain community Mongo, so `MongoVectorDBStorage` is out
without either MongoDB Atlas (cloud) or the `mongodb/mongodb-atlas-local` image.

**Consequence — the storage decision is superseded.** LightRAG now runs on its
**defaults**, all file-persisted inside the repo:

| Store | Backend |
|---|---|
| KV | `JsonKVStorage` |
| Vector | `NanoVectorDBStorage` |
| Graph | `NetworkXStorage` |
| Doc status | `JsonDocStatusStorage` |

Chosen because the original argument for Mongo was "zero new services", and the
defaults satisfy that better: `nano-vectordb` and `networkx` are **core**
dependencies of `lightrag-hku`, while every database driver (`pymongo`, `neo4j`,
`asyncpg`, `pgvector`, `qdrant-client`, …) sits in the optional `[offline-storage]`
extra and additionally needs a running service. At ~300 chunks this is not a
performance decision, and the design will be re-indexed repeatedly.

The four stores are configured independently, so a single backend can be swapped
later (e.g. Neo4j for the graph alone) without touching the others.

Rejected: MongoDB Atlas Local (heavier container, forces a decision about migrating
the bot's own data), PostgreSQL (a second database in the stack), Neo4j (deferred —
revisit only if the thesis needs Cypher-grade graph figures that
`lightrag-server`'s WebUI and the generated Obsidian vault cannot provide).

## Comments

