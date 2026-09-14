> **Single-tenant note (2026-09-06).** Runnrr is one runtime per business. Ignore every
> `tenant_id` and PR #2 reference below: sessions and audit rows carry `user_id` (an
> employee of the business) instead. `X-Admin-Token` / `ADMIN_TOKEN` are replaced by
> Supabase `require_user` (see `supabase-auth.md`). `EASYAGENT_*` env names are `RUNNRR_*`,
> `backend/` is `runnrr/`. Where this design and `docs/plans/runnrr-analysis.md` disagree,
> the analysis wins; the divergence is called out at the top of the file where it matters.

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

## Acceptance (from the contract tests on `feat/dlp-redact`)

- `test_luhn_valid_pan_is_redacted_with_last4_tag` — '4111 1111 1111 1111' → '[PAN:****1111]'; a 16-digit non-Luhn number is left alone.
- `test_ssn_and_secret_shaped_tokens_are_redacted` — '123-45-6789' → '[SSN]'; 'sk-abc…' / 'AKIA…' / 'Bearer …' → '[SECRET]'.
- `test_user_message_and_tool_results_redacted_before_provider_call` — A fake provider records the messages it receives; both the user turn and a tool result containing a PAN arrive redacted, for any provider.
- `test_redaction_happens_before_append_never_after` — The stored transcript already contains the redacted text; no message is modified after it has been appended (prefix-cache rule).
- `test_do_not_embed_front_matter_skips_indexing` — A KB file with 'do_not_embed: true' produces zero chunks in the index and is counted under 'excluded' in the index status payload.
- `test_embedded_chunks_are_redacted` — An unlabeled KB file containing a PAN is indexed with the PAN redacted; the fake embedding backend never sees the raw digits.
- `test_dlp_cannot_be_disabled_on_channel_profiles` — dlp.enabled=false on a profile with channels.sms/voice fails profile load.
