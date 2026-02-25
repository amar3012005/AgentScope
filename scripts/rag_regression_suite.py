#!/usr/bin/env python3
"""
RAG Regression Suite for SOLVIS test cases.

Runs the questions from RAG_Testtemplate.csv against the GraphRAG API and computes:
- Recall@k (expected source recall)
- Multi-source coverage
- Citation completeness
- Hallucination rate (heuristic)
- Golden-answer overlap score (heuristic)

Also supports release gating for critical test cases.
"""

import argparse
import csv
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from urllib import request as urlrequest
from urllib.error import HTTPError, URLError


CRITICAL_DEFAULT = ["TS-A02", "TS-G03", "TS-S04", "Unlabeled-02"]


STOPWORDS = {
    "der", "die", "das", "und", "oder", "ein", "eine", "the", "and", "or", "a", "an",
    "mit", "von", "zu", "for", "with", "in", "on", "of", "is", "are", "was", "were",
}


@dataclass
class CaseResult:
    test_id: str
    query: str
    expected_sources: List[str]
    retrieved_sources: List[str]
    source_recall_at_k: float
    multi_source_ok: bool
    citation_completeness: float
    hallucination_flag: bool
    answer_overlap: float
    chunks_retrieved: int
    elapsed_s: float
    error: Optional[str] = None


def normalize_source_name(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    # Handle path-like entries
    base = os.path.basename(raw)
    # Drop extension
    base = re.sub(r"\.(txt|md|pdf|docx|xlsx|pptx)$", "", base, flags=re.IGNORECASE)
    # Drop trailing hash suffixes
    base = re.sub(r"_[a-f0-9]{6,}$", "", base, flags=re.IGNORECASE)
    # Normalize separators
    base = re.sub(r"[_\-\s]+", " ", base).strip().lower()
    return base


def tokenize(text: str) -> List[str]:
    words = re.findall(r"\b[a-zA-ZäöüÄÖÜß0-9]+\b", (text or "").lower())
    return [w for w in words if len(w) >= 2 and w not in STOPWORDS]


def overlap_score(a: str, b: str) -> float:
    ta = set(tokenize(a))
    tb = set(tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta)


def parse_expected_sources(raw: str) -> List[str]:
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[;,]\s*", raw) if p.strip()]
    normalized = []
    for p in parts:
        n = normalize_source_name(p)
        if n:
            normalized.append(n)
    # dedupe, preserve order
    seen = set()
    out = []
    for n in normalized:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def extract_citation_count(answer: str) -> int:
    if not answer:
        return 0
    count = 0
    count += len(re.findall(r"\[Source:\s*[^\]]+\]", answer, flags=re.IGNORECASE))
    count += len(re.findall(r"Document\s+\[[^\]]+\],\s*Page\s*\[[^\]]+\]", answer, flags=re.IGNORECASE))
    count += len(re.findall(r"Dokument\s+\[[^\]]+\],\s*Seite\s*\[[^\]]+\]", answer, flags=re.IGNORECASE))
    return count


def extract_solvis_terms(text: str) -> set:
    return set(re.findall(r"\bSolvis[A-Za-z0-9]+\b", text or ""))


def needs_multi_source(query: str, expected_sources: List[str]) -> bool:
    q = (query or "").lower()
    if len(expected_sources) >= 2:
        return True
    return any(k in q for k in ["compare", "vergleich", "difference", "unterschied", "welche", "which", "und", "and"])


def stable_test_id(raw_id: str, unlabeled_index: int) -> Tuple[str, int]:
    rid = (raw_id or "").strip()
    if rid:
        return rid, unlabeled_index
    unlabeled_index += 1
    return f"Unlabeled-{unlabeled_index:02d}", unlabeled_index


def call_graphrag(
    base_url: str,
    api_key: str,
    query: str,
    collection_name: str,
    k: int,
    generate_answer: bool,
    timeout_s: int = 120,
) -> Dict:
    url = f"{base_url.rstrip('/')}/query/graphrag"
    payload = {
        "query": query,
        "k": k,
        "generate_answer": generate_answer,
        "collection_name": collection_name,
        "use_cache": False,
        "debug": False,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(
        url=url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else str(e)
        raise RuntimeError(f"HTTP {e.code}: {err_body[:300]}")
    except URLError as e:
        raise RuntimeError(f"Connection error: {e}")


def evaluate_case(
    case: Dict[str, str],
    test_id: str,
    base_url: str,
    api_key: str,
    collection_name: str,
    k: int,
    skip_answer: bool,
) -> CaseResult:
    query = case.get("Frage", "")
    gold = case.get("Goldene Antwort", "")
    expected_sources = parse_expected_sources(case.get("Soll-Quelle(n)", ""))

    start = time.time()
    try:
        retrieval_data = call_graphrag(
            base_url=base_url,
            api_key=api_key,
            query=query,
            collection_name=collection_name,
            k=k,
            generate_answer=False,
        )
        chunks = retrieval_data.get("chunks", [])
        retrieved_sources_raw = [c.get("doc_id", "") for c in chunks]
        retrieved_sources = []
        for d in retrieved_sources_raw:
            n = normalize_source_name(d)
            if n and n not in retrieved_sources:
                retrieved_sources.append(n)

        # Recall@k against expected source set
        matched = 0
        for exp in expected_sources:
            if any(exp in got or got in exp for got in retrieved_sources):
                matched += 1
        recall = (matched / len(expected_sources)) if expected_sources else 1.0

        answer = ""
        answer_overlap = 0.0
        citation_completeness = 0.0
        hallucination = False

        if not skip_answer:
            answer_data = call_graphrag(
                base_url=base_url,
                api_key=api_key,
                query=query,
                collection_name=collection_name,
                k=k,
                generate_answer=True,
            )
            answer = answer_data.get("answer", "")
            answer_overlap = overlap_score(gold, answer)

            citation_count = extract_citation_count(answer)
            required_citations = 2 if needs_multi_source(query, expected_sources) else 1
            citation_completeness = min(1.0, citation_count / required_citations) if required_citations else 1.0

            context_text = "\n".join(c.get("text", "") for c in chunks)
            answer_solvis = extract_solvis_terms(answer)
            context_solvis = extract_solvis_terms(context_text)
            hallucination = len(answer_solvis - context_solvis) > 0

        multi_source_ok = True
        if needs_multi_source(query, expected_sources):
            multi_source_ok = len(set(retrieved_sources)) >= 2

        elapsed = time.time() - start
        return CaseResult(
            test_id=test_id,
            query=query,
            expected_sources=expected_sources,
            retrieved_sources=retrieved_sources,
            source_recall_at_k=recall,
            multi_source_ok=multi_source_ok,
            citation_completeness=citation_completeness,
            hallucination_flag=hallucination,
            answer_overlap=answer_overlap,
            chunks_retrieved=len(chunks),
            elapsed_s=elapsed,
        )
    except Exception as e:
        return CaseResult(
            test_id=test_id,
            query=query,
            expected_sources=expected_sources,
            retrieved_sources=[],
            source_recall_at_k=0.0,
            multi_source_ok=False,
            citation_completeness=0.0,
            hallucination_flag=False,
            answer_overlap=0.0,
            chunks_retrieved=0,
            elapsed_s=time.time() - start,
            error=str(e),
        )


def summarize(results: List[CaseResult], critical_ids: List[str], skip_answer: bool) -> Dict:
    ok_results = [r for r in results if not r.error]
    failed_results = [r for r in results if r.error]

    recall_avg = statistics.mean([r.source_recall_at_k for r in ok_results]) if ok_results else 0.0
    multisource_rate = statistics.mean([1.0 if r.multi_source_ok else 0.0 for r in ok_results]) if ok_results else 0.0
    hall_rate = statistics.mean([1.0 if r.hallucination_flag else 0.0 for r in ok_results]) if ok_results else 0.0
    overlap_avg = statistics.mean([r.answer_overlap for r in ok_results]) if ok_results and not skip_answer else 0.0
    citation_avg = statistics.mean([r.citation_completeness for r in ok_results]) if ok_results and not skip_answer else 0.0

    critical = [r for r in results if r.test_id in critical_ids]
    critical_failures = []
    for r in critical:
        if r.error:
            critical_failures.append(f"{r.test_id}: execution_error")
            continue
        if r.source_recall_at_k < 1.0:
            critical_failures.append(f"{r.test_id}: source_recall<{1.0}")
        if not r.multi_source_ok:
            critical_failures.append(f"{r.test_id}: multi_source_failed")
        if not skip_answer:
            if r.citation_completeness < 1.0:
                critical_failures.append(f"{r.test_id}: citation_incomplete")
            if r.hallucination_flag:
                critical_failures.append(f"{r.test_id}: hallucination_flag")

    return {
        "cases_total": len(results),
        "cases_ok": len(ok_results),
        "cases_failed": len(failed_results),
        "avg_recall_at_k": round(recall_avg, 4),
        "multi_source_coverage_rate": round(multisource_rate, 4),
        "hallucination_rate": round(hall_rate, 4) if not skip_answer else None,
        "avg_citation_completeness": round(citation_avg, 4) if not skip_answer else None,
        "avg_answer_overlap": round(overlap_avg, 4) if not skip_answer else None,
        "critical_failures": critical_failures,
        "gate_passed": len(critical_failures) == 0 and len(failed_results) == 0,
    }


def write_reports(output_dir: Path, results: List[CaseResult], summary_data: Dict) -> Tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"rag_regression_report_{ts}.json"
    md_path = output_dir / f"rag_regression_report_{ts}.md"

    payload = {
        "summary": summary_data,
        "results": [r.__dict__ for r in results],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = []
    lines.append("# RAG Regression Report")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Cases total: {summary_data['cases_total']}")
    lines.append(f"- Cases ok: {summary_data['cases_ok']}")
    lines.append(f"- Cases failed: {summary_data['cases_failed']}")
    lines.append(f"- Avg Recall@k: {summary_data['avg_recall_at_k']}")
    lines.append(f"- Multi-source coverage: {summary_data['multi_source_coverage_rate']}")
    if summary_data.get("hallucination_rate") is not None:
        lines.append(f"- Hallucination rate: {summary_data['hallucination_rate']}")
    if summary_data.get("avg_citation_completeness") is not None:
        lines.append(f"- Citation completeness: {summary_data['avg_citation_completeness']}")
    if summary_data.get("avg_answer_overlap") is not None:
        lines.append(f"- Answer overlap: {summary_data['avg_answer_overlap']}")
    lines.append(f"- Gate passed: {summary_data['gate_passed']}")
    lines.append("")

    if summary_data["critical_failures"]:
        lines.append("## Critical Failures")
        for c in summary_data["critical_failures"]:
            lines.append(f"- {c}")
        lines.append("")

    lines.append("## Per-case")
    lines.append("| Test-ID | Recall@k | Multi-Source | Citation | Hallucination | Overlap | Error |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    for r in results:
        lines.append(
            f"| {r.test_id} | {r.source_recall_at_k:.2f} | "
            f"{'1' if r.multi_source_ok else '0'} | {r.citation_completeness:.2f} | "
            f"{'1' if r.hallucination_flag else '0'} | {r.answer_overlap:.2f} | {r.error or ''} |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def load_cases(csv_path: Path) -> List[Dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RAG regression suite from CSV test template.")
    parser.add_argument("--csv", default="/Users/amar/blaiq/RAG_Testtemplate.csv")
    parser.add_argument("--base-url", default=os.getenv("RAG_BASE_URL", "http://localhost:8002"))
    parser.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION", "graphrag_chunks"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY", ""))
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument("--skip-answer", action="store_true", help="Only run retrieval checks, skip answer generation.")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of test cases for smoke runs.")
    parser.add_argument("--critical", default=",".join(CRITICAL_DEFAULT))
    parser.add_argument("--output-dir", default="/Users/amar/blaiq/reports")
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: Missing API key. Set API_KEY env or pass --api-key", file=sys.stderr)
        return 2

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: CSV not found: {csv_path}", file=sys.stderr)
        return 2

    rows = load_cases(csv_path)
    if args.limit and args.limit > 0:
        rows = rows[:args.limit]

    results: List[CaseResult] = []
    unlabeled_index = 0
    for row in rows:
        test_id, unlabeled_index = stable_test_id(row.get("Test-ID", ""), unlabeled_index)
        print(f"Running {test_id} ...")
        result = evaluate_case(
            case=row,
            test_id=test_id,
            base_url=args.base_url,
            api_key=args.api_key,
            collection_name=args.collection,
            k=args.k,
            skip_answer=args.skip_answer,
        )
        if result.error:
            print(f"  FAIL: {result.error}")
        else:
            print(
                f"  OK: recall={result.source_recall_at_k:.2f}, "
                f"multi={int(result.multi_source_ok)}, "
                f"citation={result.citation_completeness:.2f}, "
                f"hall={int(result.hallucination_flag)}"
            )
        results.append(result)

    critical_ids = [c.strip() for c in args.critical.split(",") if c.strip()]
    summary_data = summarize(results, critical_ids, args.skip_answer)
    json_path, md_path = write_reports(Path(args.output_dir), results, summary_data)

    print("\n=== SUMMARY ===")
    print(json.dumps(summary_data, indent=2))
    print(f"\nReport JSON: {json_path}")
    print(f"Report MD:   {md_path}")

    return 0 if summary_data["gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
