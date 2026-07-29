# TTM Consultation Assistant

A LINE chatbot that acts as a Thai Traditional Medicine (TTM) self-care advisor: it chats with users in Thai, performs TTM-style tongue assessment from photos, and grounds its advice in a TTM knowledge corpus. Built as a computer science thesis project.

## Language

**Thai Traditional Medicine (TTM)**:
The domain of this system — traditional Thai medical knowledge (แพทย์แผนไทย), including tongue inspection and element-based wellness concepts.
_Avoid_: Thai healthcare, healthcare (implies modern clinical medicine)

**TTM Self-Care Advisor**:
What the bot is — an assistant that gives traditional wellness assessments and advice grounded in the TTM corpus. It never claims modern medical diagnosis and recommends seeing a doctor for anything clinically serious.
_Avoid_: doctor bot, diagnosis bot, medical chatbot

**TTM Corpus**:
The knowledge base every Assessment must be grounded in — digitized reference books embedded into the local Chroma store. Currently one book: the Thai translation of 中医临床舌诊 ("การตรวจรักษาโรคแบบแพทย์แผนจีนโดยการวินิจฉัยโรคจากลิ้น", Hu Zhen), digitized from a scanned PDF at paragraph level with book/page/paragraph provenance so retrieved passages carry a source tag the Advisor cites back to users (ADR 0008). The corpus text is copyrighted; it is committed under `corpus/` on the owner's decision because this repo is private (a purchased copy digitized for thesis use) — the repo must never be made public and `corpus/` must never be copied into a public one. Multiple books can coexist in the one collection, distinguished by `book_id`.
_Avoid_: knowledge base, training data, the documents

**Assessment**:
The bot's TTM-grounded interpretation of a user's condition (e.g., from a tongue photo or described symptoms). Deliberately not "diagnosis" in the clinical/legal sense.
_Avoid_: diagnosis, medical diagnosis

**Advisor Model**:
The text LLM that conducts the Consultation: chats in Thai, reasons over the TTM corpus, produces Assessments, and calls Health Record tools. A config-selected slot with no fixed default — any sufficiently Thai-capable model can fill it (e.g. Typhoon, GPT, Claude); swapping it is an experiment, not a rewrite. Currently filled by Gemini 2.5 Flash (same model as the Vision Describer, for now).
_Avoid_: the LLM, chatbot model, "the Typhoon model"

**Tongue Detection**:
The deterministic step that runs before the Vision Describer: it decides whether a user's photo actually shows a tongue and, if so, isolates it for description. This gate — not the Advisor — is the sole authority on "is there a tongue here?", so the advisor never assesses a photo that failed it. Three outcomes: a tongue is found (→ Tongue Description); no tongue is found (→ retake guidance, never an Assessment, turn not recorded); or the step itself fails, which is a system problem and not a bad photo (→ a system-hiccup notice asking the user to try again later).
_Avoid_: tongue recognition, image validation

**Vision Describer**:
The multimodal model that examines a cropped tongue photo and produces a Tongue Description. It describes; it never assesses. A swappable slot independent of the Advisor Model. Currently filled by Gemini 2.5 Flash (same model as the Advisor, for now).
_Avoid_: image model, vision LLM

**Tongue Description**:
The Vision Describer's structured observation of a tongue photo, with fields drawn from the TTM corpus's tongue-inspection categories (schema finalized from the book), plus a free-text notes field and an image-quality flag. Raw observation only — TTM interpretation happens later, in the Advisor Model's Tongue Assessment.
_Avoid_: image caption, image analysis

**Tongue Assessment**:
The specific kind of Assessment produced from a detected-and-cropped tongue photo: shape, color, and texture/coating interpreted through the TTM corpus. The only kind of visual Assessment the advisor performs; images without a detected tongue get guidance to retake, never an Assessment.
_Avoid_: tongue diagnosis, image analysis

**Tongue Photo**:
The kept record of a crop produced by Tongue Detection — the research dataset, and the photo "stapled to the chart" as provenance for a Tongue Assessment. Every crop is kept, including ones the confidence gate rejected (marked as rejected; those are never described, never assessed, and never shown back). A gate-passed Tongue Photo pairs the crop with the detector's confidence and the Tongue Description made from it, and is echoed back to the user after the Assessment reply. Deliberately outside Consultation memory: it survives regardless of the Relevance Gate, is not part of the Working Buffer or Health Record lifecycle, and is never written to the Health Profile. Users are told at first contact that photos are kept for research.
_Avoid_: profile image, user image, chat attachment, image log

**Consultation**:
A bounded episode of interaction between a user and the advisor, analogous to one doctor visit. Closed by an inactivity gap, at which point it passes the Relevance Gate: clinically relevant Consultations are summarized into a Health Record entry; the rest (memes, greetings, off-topic chat) are discarded. A user has many Consultations over time.
_Avoid_: session, chat, thread

**Working Buffer**:
The raw, per-user store of turns for the currently-open Consultation (role, text, timestamp). Each turn, the spine replays its recent turns to the Advisor as within-Consultation memory — the Advisor itself has no tool to query it. Exists only until the Consultation closes, at which point the Relevance Gate summarizes it and it is deleted — never itself a form of long-term memory.
_Avoid_: conversation history, chat log, session store

**Relevance Gate**:
The check at Consultation close that decides whether the exchange contained health-relevant content. Only Consultations that pass produce Health Record entries, keeping the record as clean as a doctor's chart.
_Avoid_: spam filter, content filter

**Health Record**:
The per-user persistent memory, mirroring a doctor's notes: a series of record entries, each holding structured observations (symptoms, Assessments, advice) plus a summary of the conversation that produced them. The only long-term memory — raw transcripts are not persisted — and the sole source from which the Health Profile is derived.
_Avoid_: conversation history, chat log, transcript

**Health Profile**:
The per-user face sheet: a single current-state view holding TTM identity (birth date, sex, and the ธาตุเจ้าเรือน derived from birth date), clinical background (chronic conditions, allergies, regular medicines and herbs), lifestyle habits, and Ongoing Complaints. Derived exclusively from Health Record entries — rebuildable from them at any time — and read by the Advisor every turn, but never writable by it.
_Avoid_: patient profile, user profile, patient record

**Profile Updater**:
The deterministic step at Consultation close that folds a gate-passed Health Record entry into the Health Profile as precise item-level changes — never a rewrite of the whole sheet. LLM-scored but code-triggered, like the Relevance Gate; the Advisor cannot invoke it.
_Avoid_: memory tool, save tool, profile agent

**Topic Menu**:
The short list of follow-up topics the Advisor offers after a reply, shown to the user as tappable buttons rather than text. Each topic is a drill-down into content the Advisor deliberately held back to keep the reply to one phone screen; it may also include an intake item from the Health Profile's missing-information list, making that intake user-initiated. Part of the advisor turn in the Working Buffer, so the offer survives even after the buttons disappear from the chat. Never accompanies a red-flag escalation. Distinct from an intake question: the menu offers what the *user* may ask next, an intake question asks for the user's own information.
_Avoid_: quick replies (the transport, not the concept), suggested questions, follow-up list

**Ongoing Complaint**:
An open item on the Health Profile tracking a condition across Consultations (e.g. persistent insomnia), like a doctor's follow-up list. Cleared when the user reports it resolved.
_Avoid_: active issue, open ticket, symptom log
