# Tongue Photos: standalone dataset collection, echoed via self-hosted capability URLs

Every crop the Roboflow workflow returns is persisted as a [Tongue Photo](../../CONTEXT.md) — one document per crop in a new `tongue_photos` collection, deliberately **outside** the memory architecture (Working Buffer, Relevance Gate, Health Record, Health Profile). The document stores the JPEG as BSON `Binary` (not base64), plus `user_id`, a UUID4 `photo_id`, `captured_at`, the detector's `confidence`, `passed_gate`, `line_message_id`, and a nullable Tongue Description. Gate-passed crops are echoed back to the user in the same reply as the Assessment: one reply call carrying `[TextMessage, ImageMessage]`, with the Topic Menu Quick Reply moved onto the ImageMessage. The ImageMessage URLs point at a new unauthenticated read-only endpoint, `GET /tongue-photos/{photo_id}`, served by the app itself through its public HTTPS tunnel (`PUBLIC_BASE_URL` config).

## Why

- **The purpose is a thesis dataset first, chart provenance second.** That purpose dictates the boundary decision: the Working Buffer is deleted at Consultation close and gate-failed Consultations are discarded, so anything inside that lifecycle would lose data. Tongue Photos survive regardless of the Relevance Gate.
- **The Health Profile was never an option**, despite being the intuitive home ("save it on the user's profile"): ADR 0003 makes the profile a rebuildable projection of Health Record entries with a single write path (the Profile Updater at gate-passed close). An image written at turn time would break both invariants.
- **No foreign key to Health Records.** Record entries are written at Consultation close, long after the photo document exists; linking them would thread photo IDs through the gate summary for zero analytical value. `user_id` + timestamp correlation identifies the Consultation window.
- **BSON Binary over base64** (the originally proposed encoding): base64 inflates ~33% and adds an encode/decode step per read/write for no benefit. The crop arrives from Roboflow as base64, is decoded to a PIL image once (ADR 0004), and is saved as JPEG bytes. Cropped tongues run tens–hundreds of KB, far under the 16 MB document cap, so GridFS/object storage is overhead.
- **Insert after detect, update after describe.** The document is written the moment detection succeeds, with `description: null`; the Tongue Description is patched in when the Vision Describer returns. A describer outage (previously: everything lost) now still captures the crop, and a null description marks exactly which stage failed.
- **Below-threshold crops are kept too** (`passed_gate: false`). The workflow returns a crop even when the app-side confidence gate rejects it (ADR 0004); discarding it forecloses threshold-calibration / false-reject analysis. Rejected crops are never described, never assessed, never echoed — the user-facing retake flow is unchanged.
- **Self-hosted capability URLs** because a LINE `ImageMessage` is two public HTTPS URLs LINE's servers fetch — bytes cannot be pushed. The bytes already live in Mongo, so one read-only endpoint finishes the job; external object storage would be a second infrastructure dependency for nothing. Security is the capability URL itself: `photo_id` is a UUID4, **never** a Mongo ObjectId (ObjectIds are timestamp-based and enumerable). The same JPEG serves as both `originalContentUrl` and `previewImageUrl` (crops sit under LINE's 1 MB preview cap).
- **Quick Reply rides on the ImageMessage** because LINE renders Quick Reply buttons only under the last message in the chat; bundling `[text+topics, image]` or pushing the image separately would hide the Topic Menu.

## Failure contract

The image must never cost the user their Assessment. The delivery chain degrades one rung at a time: reply `[text, image+topics]` → push `[text, image+topics]` → push `[text+topics]` → push `[text]` — extending the existing degrade-to-text philosophy (ADR 0006, `reply_or_push`). Retake-guidance and system-hiccup replies stay image-free. Save failures are logged, never surfaced: a Mongo write error must not turn a good photo turn into a hiccup message.

## Considered and rejected

- **Crop + original uncropped bytes**: rejected for scope (crop only). Accepted limitation, on record: LINE's content API retains message content only transiently, so originals are unrecoverable later and detector-quality evaluation leans on the crops themselves. `line_message_id` is stored anyway — it is free and works within the retention window.
- **TTL / auto-deletion**: contradicts the dataset purpose. Retention is indefinite, disclosed by one sentence added to the `follow` welcome message (photos sent for tongue assessment are kept for research).

## Consequences

- The serving endpoint is unauthenticated by design (LINE's fetchers and the user's client GET it without credentials). Possession of the UUID is the authorization. Do not add photo listing/enumeration endpoints.
- Old image messages in chats re-fetch from the tunnel: if the tunnel or app is down, historical images stop rendering. Acceptable for a thesis deployment.
- Changing `PUBLIC_BASE_URL` (e.g. a new tunnel hostname) breaks images already delivered to chats — their URLs are frozen in LINE's message history.
- `TongueDetector`'s contract widens: "detected but below the gate" (crop exists, rejected) must be distinguishable from "nothing detected" (no crop), where both were previously `None`.
- Dataset browsing is script-export (images-in-BSON are not Finder-friendly); accepted for thesis-scale volume.
