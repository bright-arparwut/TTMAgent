# 08 — Concept-note generation and vault layout

Status: ready-for-human
Type: wayfinder:grilling
Map: ../MAP.md
Blocked by: 07

## Question

The vault is `sources/` (hand-editable, from OCR) plus `concepts/` (generated from
the graph). Pin how concept notes are produced and what the vault looks like.

- **One note per entity, or per entity above some threshold?** The spike will show
  the entity count; a graph with hundreds of one-mention entities makes an unusable
  vault.
- **What is inside a Concept note?** LightRAG generates entity descriptions —
  are those the note body, or is the note just a hub of links?
- **Wikilinks** — relations become `[[links]]`. Is the relation type carried
  (`[[ธาตุไฟ]]` vs `กำเริบทำให้ [[อาการร้อนใน]]`)? Obsidian renders unlabelled links
  only, so labelled edges need a convention.
- **Frontmatter** — what does a Concept note carry so it can be regenerated and
  traced back to source sections?
- **Regeneration** — `concepts/` is derived, so a rebuild overwrites it. Committed
  to git or gitignored? What happens if someone edits a concept note by hand?
- **Does anything read the vault at runtime?** Per the map, no — Obsidian is a view.
  Confirm the generated vault is genuinely write-only from the system's side.

## Why it matters

This is the part the effort started from: seeing the TTM knowledge graph in Obsidian.
It is also where thesis figures come from.

## Comments
