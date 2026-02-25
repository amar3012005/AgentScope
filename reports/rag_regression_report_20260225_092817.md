# RAG Regression Report

## Summary
- Cases total: 19
- Cases ok: 18
- Cases failed: 1
- Avg Recall@k: 0.0556
- Multi-source coverage: 0.1667
- Hallucination rate: 0.0
- Citation completeness: 0.0
- Answer overlap: 0.0
- Gate passed: False

## Critical Failures
- TS-A02: source_recall<1.0
- TS-A02: multi_source_failed
- TS-A02: citation_incomplete
- TS-G03: source_recall<1.0
- TS-G03: multi_source_failed
- TS-G03: citation_incomplete
- TS-S04: source_recall<1.0
- TS-S04: multi_source_failed
- TS-S04: citation_incomplete
- Unlabeled-02: multi_source_failed
- Unlabeled-02: citation_incomplete

## Per-case
| Test-ID | Recall@k | Multi-Source | Citation | Hallucination | Overlap | Error |
|---|---:|---:|---:|---:|---:|---|
| TS-A01 | 0.00 | 0 | 0.00 | 0 | 0.00 |  |
| TS-A02 | 0.00 | 0 | 0.00 | 0 | 0.00 |  |
| TS-G01 | 0.00 | 0 | 0.00 | 0 | 0.00 |  |
| TS-G02 | 0.00 | 0 | 0.00 | 0 | 0.00 | HTTP 404: {"detail":"No relevant chunks found"} |
| TS-S01 | 0.00 | 1 | 0.00 | 0 | 0.00 |  |
| TS-S02 | 0.00 | 0 | 0.00 | 0 | 0.00 |  |
| TS-H01 | 0.00 | 0 | 0.00 | 0 | 0.00 |  |
| TS-N01 | 0.00 | 1 | 0.00 | 0 | 0.00 |  |
| TS-N02 | 0.00 | 0 | 0.00 | 0 | 0.00 |  |
| TS-A03 | 0.00 | 0 | 0.00 | 0 | 0.00 |  |
| TS-A04 | 0.00 | 0 | 0.00 | 0 | 0.00 |  |
| TS-A05 | 0.00 | 0 | 0.00 | 0 | 0.00 |  |
| TS-G03 | 0.00 | 0 | 0.00 | 0 | 0.00 |  |
| TS-S03 | 0.00 | 0 | 0.00 | 0 | 0.00 |  |
| TS-S04 | 0.00 | 0 | 0.00 | 0 | 0.00 |  |
| TS-H02 | 0.00 | 0 | 0.00 | 0 | 0.00 |  |
| Unlabeled-01 | 0.00 | 1 | 0.00 | 0 | 0.00 |  |
| Unlabeled-02 | 1.00 | 0 | 0.00 | 0 | 0.00 |  |
| Unlabeled-03 | 0.00 | 0 | 0.00 | 0 | 0.00 |  |