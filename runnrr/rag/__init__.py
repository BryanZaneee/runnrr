"""Retrieval-augmented generation building blocks.

Each Runnrr profile carries its own portable index under
profiles/<id>/.index/ (one sqlite-vec file + one BM25 pickle + a manifest).
`semantic_search_kb` reaches this package additively beside the existing
`search_kb` keyword path.
"""
