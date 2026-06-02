"""BM25 sparse retrieval index.

Ported from Anthropic-course/004_bm25.ipynb with save/load added for on-disk
persistence per profile. The course's exp(-k*raw_score) post-transform turns
BM25 scores into a monotonically-decreasing "distance" so smaller values are
better, which lets the hybrid Retriever fuse BM25 with vector cosine-distance
scores without sign juggling.
"""
from __future__ import annotations

import math
import pickle
import re
from collections import Counter
from pathlib import Path
from typing import Callable

from backend.rag.chunker import Chunk

PICKLE_PROTOCOL = 4
_STATE_VERSION = 1


class BM25Index:
    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        tokenizer: Callable[[str], list[str]] | None = None,
    ):
        self.chunks: list[Chunk] = []
        self._corpus_tokens: list[list[str]] = []
        self._doc_len: list[int] = []
        self._doc_freqs: dict[str, int] = {}
        self._avg_doc_len: float = 0.0
        self._idf: dict[str, float] = {}
        self._index_built: bool = False
        self.k1 = k1
        self.b = b
        self._tokenizer = tokenizer if tokenizer else self._default_tokenizer

    @staticmethod
    def _default_tokenizer(text: str) -> list[str]:
        tokens = re.split(r"\W+", text.lower())
        return [t for t in tokens if t]

    def add(self, chunk: Chunk) -> None:
        if not isinstance(chunk, Chunk):
            raise TypeError("chunk must be a Chunk.")
        tokens = self._tokenizer(chunk.content)
        self.chunks.append(chunk)
        self._record_tokens(tokens)
        self._index_built = False

    def _record_tokens(self, tokens: list[str]) -> None:
        self._corpus_tokens.append(tokens)
        self._doc_len.append(len(tokens))
        seen: set[str] = set()
        for tok in tokens:
            if tok not in seen:
                self._doc_freqs[tok] = self._doc_freqs.get(tok, 0) + 1
                seen.add(tok)

    def _rebuild_token_stats(self) -> None:
        self._corpus_tokens = []
        self._doc_len = []
        self._doc_freqs = {}
        for chunk in self.chunks:
            self._record_tokens(self._tokenizer(chunk.content))
        self._index_built = False

    def delete_by_path(self, rel_path: str) -> int:
        before = len(self.chunks)
        self.chunks = [chunk for chunk in self.chunks if chunk.path != rel_path]
        deleted = before - len(self.chunks)
        if deleted:
            self._rebuild_token_stats()
        return deleted

    def _build_index(self) -> None:
        if not self.chunks:
            self._avg_doc_len = 0.0
            self._idf = {}
            self._index_built = True
            return
        self._avg_doc_len = sum(self._doc_len) / len(self.chunks)
        n = len(self.chunks)
        self._idf = {
            term: math.log(((n - freq + 0.5) / (freq + 0.5)) + 1)
            for term, freq in self._doc_freqs.items()
        }
        self._index_built = True

    def _score(self, query_tokens: list[str], doc_index: int) -> float:
        score = 0.0
        counts = Counter(self._corpus_tokens[doc_index])
        doc_len = self._doc_len[doc_index]
        for tok in query_tokens:
            idf = self._idf.get(tok)
            if idf is None:
                continue
            tf = counts.get(tok, 0)
            num = idf * tf * (self.k1 + 1)
            den = tf + self.k1 * (
                1 - self.b + self.b * (doc_len / self._avg_doc_len)
            )
            score += num / (den + 1e-9)
        return score

    def search(
        self,
        query_text: str,
        k: int = 5,
        score_normalization_factor: float = 0.1,
    ) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        if k <= 0:
            raise ValueError("k must be a positive integer.")
        if not self._index_built:
            self._build_index()
        if self._avg_doc_len == 0:
            return []
        query_tokens = self._tokenizer(query_text)
        if not query_tokens:
            return []
        raw: list[tuple[float, Chunk]] = []
        for i in range(len(self.chunks)):
            s = self._score(query_tokens, i)
            if s > 1e-9:
                raw.append((s, self.chunks[i]))
        raw.sort(key=lambda item: item[0], reverse=True)
        out: list[tuple[Chunk, float]] = []
        for raw_score, chunk in raw[:k]:
            normalized = math.exp(-score_normalization_factor * raw_score)
            out.append((chunk, normalized))
        out.sort(key=lambda item: item[1])
        return out

    def __len__(self) -> int:
        return len(self.chunks)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "version": _STATE_VERSION,
            "k1": self.k1,
            "b": self.b,
            "chunks": self.chunks,
        }
        with path.open("wb") as f:
            pickle.dump(state, f, protocol=PICKLE_PROTOCOL)

    @classmethod
    def load(cls, path: Path) -> "BM25Index":
        with path.open("rb") as f:
            state = pickle.load(f)
        idx = cls(k1=state["k1"], b=state["b"])
        idx.chunks = state["chunks"]
        idx._rebuild_token_stats()
        return idx
