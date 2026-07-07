# Tongue detection and crop move server-side into a Roboflow workflow

`TongueDetector` calls a Roboflow serverless **workflow** (`tongue-detect-crop` on `serverless.roboflow.com`) instead of the bare hosted-model endpoint. The workflow detects the tongue, keeps only the top-1 detection, crops server-side, and returns two outputs the app consumes per image: `output_crops` (base64 crops — bare strings via the inference SDK, `{"type": "base64", "value": ...}` dicts via raw HTTP; the app accepts both) and `predictions` (bounding boxes with confidences, nested as `predictions.predictions`). Extra outputs (`count_objects`, `output_image`) are ignored. The app decodes the crop as the Vision Describer's input and applies its own confidence threshold to the predictions — the deterministic "Tongue found?" diamond in [message-flow](../message-flow.md) stays in app code, tunable via `ROBOFLOW_CONFIDENCE_THRESHOLD` without touching the workflow.

## Why

- One round-trip returns both the decision data and the describer input; the app no longer re-implements crop geometry (the old local `_crop_with_padding` and `ROBOFLOW_CROP_PADDING_RATIO` are gone).
- Crop logic lives next to the model that produces the boxes, so retraining and re-cropping evolve together in the Roboflow console.
- Keeping the threshold app-side keeps the documented decision boundary in the repo — versioned, testable, and visible in config.

## Console-side invariants

The repo cannot enforce these; they live in the Roboflow workflow definition and hold the contract together. Re-check both after **any** console edit:

1. **Top-1 filter** — a detections filter keeps at most one detection, so `output_crops` and `predictions.predictions` each carry ≤ 1 entry. The app still pairs crop↔prediction by argmax confidence and raises on a length mismatch, as insurance.
2. **Output names** — the code reads outputs named `output_crops` and `predictions` (verified against the live workflow 2026-07-07). Renaming either in the console breaks every image turn with a `TongueDetectionError`.
3. **Threshold hierarchy** — the workflow's model-node confidence threshold (~0.25) must stay *below* `ROBOFLOW_CONFIDENCE_THRESHOLD` (default 0.5). If the console value climbs above the app value, the app-side gate silently becomes dead code.

## Failure contract

`detect_and_crop` distinguishes three outcomes: a `CroppedTongue`; a clean "no tongue" (`None` → Thai retake guidance, turn not recorded — unchanged); and `TongueDetectionError` for network, timeout (30 s), or contract violations. The dispatcher turns any detector/describer failure into a Thai "system hiccup, try again later" reply — an outage is never presented as a bad photo, which would send users into pointless retake loops.

## Consequences

- Editing the workflow in the Roboflow console can break production without any repo change — the invariants above are the checklist.
- The crop is exactly the detection bbox (no padding). If the Vision Describer proves to need context around the tongue, padding belongs in the workflow's crop node, not in app code.
- `use_cache=False` on every call: console edits take effect immediately, at the cost of re-fetching the workflow definition per request.
- Every tongue turn still costs one Roboflow round-trip plus one Describer call; the workflow adds no extra network hop over the old model endpoint.
