# feat/dlp-redact

**Status:** prepared (design + skipped contract tests). No implementation yet.

## Problem

Customers will paste card numbers, SSNs, and the occasional API key into an inbox or SMS thread. Today that text goes verbatim to the model provider and, via RAG indexing, into an embeddings vendor. Runnrr sells enterprise model APIs with a data story; the engine needs a floor: no PAN/SSN/secret leaves the box in plaintext, and a document a business marks "do not embed" is never indexed.

## Design

- `backend/dlp.py`, stdlib `re` only. Detectors: PAN (13–19 digits with separators **and** passing Luhn — avoids redacting order numbers), US SSN (`\d{3}-\d{2}-\d{4}` with the standard invalid-prefix exclusions), and secret-shaped tokens (`sk-`, `AIza`, `xoxb-`, `ghp_`, `AKIA`, JWT `eyJ…` triples, `Bearer …`). Replacement is type-tagged: `[PAN:****1234]`, `[SSN]`, `[SECRET]` — the model can still say "the card ending 1234".
- **Where it runs — one place.** `redact()` is applied in the agent loop to the user message and to every tool result **before** the provider call (`run_conversation_stream`), so all five providers are covered without touching them. What was redacted is logged as counts per type to the audit log (feat/audit-log-kill-switch), never the raw value.
- Redaction is applied to the text that enters the transcript, so the stored/cached prefix is already redacted (prefix-cache rule: we redact before append, never edit after).
- **"Do not embed" label in RAG.** A KB file whose front matter has `do_not_embed: true`, or whose path is listed in the profile's `rag.exclude` globs, is skipped by `backend/rag/indexer.py` and reported in `backend/rag/cli.py info` / `GET /api/rag/index` as `excluded: N`. `search_kb` (literal grep) still works on those files — the label is about what leaves the box, not local reads. Chunks of embedded files are also passed through `redact()` so an unlabeled document with a PAN in it doesn't ship the PAN to the embeddings vendor.
- Per-profile knob: `"dlp": {"enabled": true, "types": ["pan","ssn","secret"]}`; default on for every profile. Disabling is allowed only for profiles with no channels (dev/demo).

## API sketch

No new endpoints. `GET /api/rag/index` gains `excluded`. Audit records gain `dlp: {"pan": 1, "ssn": 0, "secret": 0}`.

```python
def redact(text: str, types: frozenset[str] = DEFAULT_TYPES) -> tuple[str, dict[str, int]]: ...
```

## Tests to write

See `tests/test_dlp_redact_contract.py` (skipped). Uses well-known test PANs (4111 1111 1111 1111) and a non-Luhn 16-digit number as the negative case.

## Out of scope

Classifier training, ML/NER-based PII (names, addresses), redacting model *output*, per-tenant custom patterns, non-US identifiers.

## Dependencies

None hard. feat/audit-log-kill-switch for the redaction counts sink.
