# Alpha

Project Alpha is a portable agent framework written in Python. It powers
several customer-facing demos and is the canonical reference implementation
for hybrid retrieval inside the EasyAgent ecosystem.

## Overview

The Alpha runtime owns its own knowledge base, vector store, and tool registry.
Profiles are loaded from disk and provide all persona-specific behavior. The
runtime never embeds business logic itself; it merely orchestrates.

## Architecture

The agent loop dispatches normalized provider events. Tool calls fan out to
small Python handlers, and tool results are appended back into the message
history before the next provider hop. Bounded loops, structured logs, and
strict tool allowlists keep the surface area small and inspectable.

## Performance

Search latency on a typical profile is dominated by the LLM rerank step. The
underlying sqlite-vec lookup is sub-millisecond; BM25 is similarly fast. The
rerank call adds roughly half a second when enabled and can be disabled per
profile when speed matters more than fine-grained ordering.
