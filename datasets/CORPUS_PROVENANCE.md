# Corpus Provenance

This file lives outside `tech_docs/` on purpose. Every markdown file in that folder is indexed by the benchmarks, so notes about the corpus must not be added there.

This is not an untouched snapshot of the official documentation. A small set
of early files was adapted from the official docs listed below. Most files,
roughly 170 of 200, were written by an LLM with `scripts/generate_tech_docs.py`
from a per-framework topic list, in the style of that documentation. The
generated files were checked for length and format, not reviewed line by line
for technical accuracy. Treat the corpus as a retrieval test bed, not as a
reference for the frameworks it describes.

The questions and expected answers in `datasets/synthetic_queries/` were also
LLM-generated with `scripts/generate_queries.py`. See the `label_policy` field
in each query file for how source labels were assigned.
