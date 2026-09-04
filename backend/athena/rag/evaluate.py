"""
AERO-ASTRA — ATHENA RAG: Evaluation Script
============================================
Measures retrieval performance of the RAG pipeline using standard metrics.

Metrics computed:
    - Hit Rate @K    : fraction of queries where ≥1 relevant passage in top-K
    - Precision @K   : fraction of top-K results that are relevant (avg across queries)
    - Recall @K      : fraction of total relevant passages retrieved in top-K
    - MRR @K         : Mean Reciprocal Rank — rank position of first relevant hit
    - Avg Relevance  : mean cosine similarity (1 − distance) across all retrieved passages
    - Latency        : wall-clock retrieval time per query (ms)

Primary test suite — the three demo-safe simulator faults:
    - tcs_thermal_runaway
    - ttc_signal_dropout
    - propulsion_thruster_fault

Extended test suite covers all 6 FDIR fault domains for a broader baseline.

Outputs:
    - Terminal: coloured summary box (ASCII art)
    - Markdown: backend/athena/rag/EVAL_REPORT.md (auto-generated, timestamped)

Usage:
    python -m backend.athena.rag.evaluate                  # full suite
    python -m backend.athena.rag.evaluate --demo-only      # 3 demo faults only
    python -m backend.athena.rag.evaluate --top-k 6        # change K
    python -m backend.athena.rag.evaluate --out report.md  # custom output path
"""

from __future__ import annotations

import datetime
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("athena.rag.evaluate")

# ─────────────────────────────────────────────────────────────────────────────
# Ground-truth evaluation set
# ─────────────────────────────────────────────────────────────────────────────
# Each entry mirrors a realistic SherlockDiagnosis (primary_root_cause +
# affected_subsystems + causal_chain fused into a query string).
# `keywords` are the minimum vocabulary the relevant passage MUST contain.
# `relevant_sections` maps to expected NASA-HDBK-1002 section references for
# Recall@K computation (we count how many distinct sections are retrieved).

# ── Demo-safe faults (the three the judges will see) ──────────────────────────
DEMO_QUERIES: list[dict] = [
    {
        "fault_id": "tcs_thermal_runaway",
        "query": (
            "thermal runaway satellite temperature exceeding limits "
            "heater circuit failure TCS eclipse battery temperature HIGH"
        ),
        "keywords": ["thermal", "temperature", "heater", "TCS", "eclipse"],
        "relevant_sections": ["§6.1", "§6.2", "§6.3"],
        "description": "TCS Thermal Runaway",
        "expected_actions": ["safe_mode", "heater_control", "attitude_adjustment"],
    },
    {
        "fault_id": "ttc_signal_dropout",
        "query": (
            "telemetry signal loss communication dropout ground station link "
            "TTC uplink downlink degradation MEDIUM"
        ),
        "keywords": ["communication", "telemetry", "signal", "link", "ground"],
        "relevant_sections": ["§8.1", "§8.2", "§8.3"],
        "description": "TT&C Signal Dropout",
        "expected_actions": ["antenna_realignment", "power_boost", "safe_mode"],
    },
    {
        "fault_id": "propulsion_thruster_fault",
        "query": (
            "thruster anomaly propulsion fault attitude disturbance fuel leak "
            "maneuver abort spacecraft safing HIGH"
        ),
        "keywords": ["thruster", "propulsion", "fuel", "maneuver", "fault"],
        "relevant_sections": ["§7.1", "§7.2", "§7.3"],
        "description": "Propulsion Thruster Fault",
        "expected_actions": ["thruster_isolation", "safe_mode", "fuel_crossfeed"],
    },
]

# ── Extended suite — all 6 FDIR domains ───────────────────────────────────────
EXTENDED_QUERIES: list[dict] = DEMO_QUERIES + [
    {
        "fault_id": "eps_battery_degradation",
        "query": (
            "battery state-of-charge degradation EPS power bus low voltage "
            "load shedding solar array eclipse HIGH"
        ),
        "keywords": ["battery", "power", "charge", "EPS", "degradation"],
        "relevant_sections": ["§5.1", "§5.2", "§5.3", "§10.3"],
        "description": "EPS Battery Degradation",
        "expected_actions": ["load_shedding", "safe_mode", "battery_reconditioning"],
    },
    {
        "fault_id": "adcs_reaction_wheel",
        "query": (
            "reaction wheel failure attitude control ADCS momentum desaturation "
            "tumbling spacecraft pointing loss MEDIUM"
        ),
        "keywords": ["reaction wheel", "attitude", "ADCS", "momentum", "desaturation"],
        "relevant_sections": ["§4.1", "§4.2", "§4.3"],
        "description": "ADCS Reaction Wheel Fault",
        "expected_actions": ["momentum_dump", "safe_mode", "thruster_attitude"],
    },
    {
        "fault_id": "eps_cascade_failure",
        "query": (
            "power bus cascade failure under-voltage lockout load priority "
            "EPS total power loss recovery"
        ),
        "keywords": ["power", "bus", "voltage", "load", "shedding"],
        "relevant_sections": ["§5.3", "§10.3"],
        "description": "EPS Cascade Power Failure",
        "expected_actions": ["emergency_load_shed", "safe_mode"],
    },
    {
        "fault_id": "general_fdir",
        "query": (
            "fault detection isolation recovery FDIR autonomy design principles "
            "spacecraft safe mode transition"
        ),
        "keywords": ["FDIR", "detection", "isolation", "recovery", "design"],
        "relevant_sections": ["§2.1", "§2.2", "§3.1"],
        "description": "General FDIR Principles",
        "expected_actions": ["safe_mode"],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class QueryResult:
    fault_id: str
    query: str
    description: str
    retrieved_passages: list[dict]
    keywords: list[str]
    relevant_sections: list[str]

    # Core metrics
    hit: bool              # ≥1 relevant passage in top-K
    reciprocal_rank: float # 1/rank of first relevant hit; 0.0 on miss
    precision_at_k: float  # relevant_retrieved / K
    recall_at_k: float     # relevant_retrieved / total_relevant_in_kb
    avg_relevance: float   # mean cosine sim across top-K
    latency_ms: float

    matched_keywords: list[str] = field(default_factory=list)
    relevant_count: int = 0  # passages in top-K judged relevant


@dataclass
class EvalReport:
    suite_name: str
    top_k: int
    num_queries: int
    hit_rate: float
    mrr: float
    precision_at_k: float
    recall_at_k: float
    avg_relevance: float
    avg_latency_ms: float
    results: list[QueryResult]
    generated_at: str = ""

    def summary(self) -> str:
        """Terminal-friendly ASCII summary box."""
        w = 66
        sep = "╠" + "═" * w + "╣"
        lines = [
            "╔" + "═" * w + "╗",
            f"║  ATHENA RAG — {self.suite_name} (top_k={self.top_k})".ljust(w + 1) + "║",
            f"║  Generated : {self.generated_at}".ljust(w + 1) + "║",
            sep,
            f"║  Queries evaluated : {self.num_queries}".ljust(w + 1) + "║",
            f"║  Hit Rate @{self.top_k}       : {self.hit_rate:.1%}".ljust(w + 1) + "║",
            f"║  Precision @{self.top_k}      : {self.precision_at_k:.3f}".ljust(w + 1) + "║",
            f"║  Recall @{self.top_k}         : {self.recall_at_k:.3f}".ljust(w + 1) + "║",
            f"║  MRR @{self.top_k}            : {self.mrr:.3f}".ljust(w + 1) + "║",
            f"║  Avg Relevance      : {self.avg_relevance:.3f}  (cosine similarity)".ljust(w + 1) + "║",
            f"║  Avg Latency        : {self.avg_latency_ms:.1f} ms / query".ljust(w + 1) + "║",
            sep,
            "║  Per-Query Results:".ljust(w + 1) + "║",
        ]
        for r in self.results:
            icon = "✓" if r.hit else "✗"
            line = (
                f"║  {icon} [{r.reciprocal_rank:.2f} RR | P={r.precision_at_k:.2f} "
                f"| R={r.recall_at_k:.2f} | {r.avg_relevance:.2f} sim | {r.latency_ms:.0f}ms]"
            )
            lines.append(line.ljust(w + 1) + "║")
            lines.append(f"║    {r.description}".ljust(w + 1) + "║")
            if r.matched_keywords:
                lines.append(f"║    keywords: {', '.join(r.matched_keywords)}".ljust(w + 1) + "║")
        lines.append("╚" + "═" * w + "╝")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Relevance helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_relevant(passage: str, keywords: list[str], min_matches: int = 2) -> bool:
    """
    Heuristic relevance judge: passage must contain ≥ min_matches of the
    required keywords (case-insensitive). Matches multi-word keywords like
    'reaction wheel' as a substring.
    """
    pl = passage.lower()
    return sum(1 for kw in keywords if kw.lower() in pl) >= min_matches


def _count_section_hits(passages: list[dict], sections: list[str]) -> int:
    """
    Count how many of the expected relevant_sections are cited in the
    retrieved passage texts (e.g. '§5.2' or 'Section 5.2').
    """
    hits = 0
    for section in sections:
        # Match §5.2 or Section 5.2 or 5.2 as substring
        bare = section.lstrip("§")
        for p in passages:
            text = p["text"]
            if section in text or f"Section {bare}" in text or f"section {bare}" in text:
                hits += 1
                break
    return hits


# ─────────────────────────────────────────────────────────────────────────────
# Core evaluation logic
# ─────────────────────────────────────────────────────────────────────────────

def evaluate(
    pipeline,
    queries: list[dict] | None = None,
    top_k: int | None = None,
    suite_name: str = "Evaluation Suite",
) -> EvalReport:
    """
    Run the evaluation queries against a built AthenaRAGPipeline.

    Args:
        pipeline:   An AthenaRAGPipeline instance (must be ready).
        queries:    Query dicts to evaluate (default: EXTENDED_QUERIES).
        top_k:      Number of passages to retrieve (default: pipeline.top_k).
        suite_name: Label used in the report header.

    Returns:
        EvalReport with all metrics.
    """
    if not pipeline.is_ready():
        raise RuntimeError(
            "RAG pipeline is not ready. Call pipeline.build() or "
            "pipeline.ensure_ready() before evaluating."
        )

    queries = queries or EXTENDED_QUERIES
    effective_k = top_k or pipeline.top_k
    query_results: list[QueryResult] = []

    for q in queries:
        query_text = q["query"]
        keywords   = q.get("keywords", [])
        sections   = q.get("relevant_sections", [])

        t0 = time.perf_counter()
        raw = pipeline.retrieve_raw(query_text)
        latency_ms = (time.perf_counter() - t0) * 1000

        top_k_raw = raw[:effective_k]

        # ── relevance per passage ────────────────────────────────────────────
        hit = False
        reciprocal_rank = 0.0
        relevant_count = 0
        matched_kw: list[str] = []

        for rank, item in enumerate(top_k_raw, start=1):
            if _is_relevant(item["text"], keywords):
                relevant_count += 1
                if not hit:
                    hit = True
                    reciprocal_rank = 1.0 / rank
                matched_kw.extend(
                    kw for kw in keywords if kw.lower() in item["text"].lower()
                )

        # ── Precision@K = relevant_in_top_k / K ────────────────────────────
        precision_at_k = relevant_count / effective_k if effective_k else 0.0

        # ── Recall@K = relevant_in_top_k / total_relevant_in_kb ────────────
        # Total relevant approximated by number of expected relevant sections
        # (lower-bound estimate; safe for comparison purposes).
        total_relevant = max(len(sections), 1)
        recall_at_k = min(relevant_count / total_relevant, 1.0)

        # ── Avg cosine similarity ───────────────────────────────────────────
        avg_rel = (
            sum(item["relevance"] for item in top_k_raw) / len(top_k_raw)
            if top_k_raw else 0.0
        )

        query_results.append(QueryResult(
            fault_id=q.get("fault_id", "unknown"),
            query=query_text,
            description=q.get("description", query_text[:60]),
            retrieved_passages=raw,
            keywords=keywords,
            relevant_sections=sections,
            hit=hit,
            reciprocal_rank=reciprocal_rank,
            precision_at_k=precision_at_k,
            recall_at_k=recall_at_k,
            avg_relevance=avg_rel,
            latency_ms=latency_ms,
            matched_keywords=list(dict.fromkeys(matched_kw)),
            relevant_count=relevant_count,
        ))

    # ── Aggregate metrics ────────────────────────────────────────────────────
    n = len(query_results)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return EvalReport(
        suite_name=suite_name,
        top_k=effective_k,
        num_queries=n,
        hit_rate=sum(r.hit for r in query_results) / n,
        mrr=sum(r.reciprocal_rank for r in query_results) / n,
        precision_at_k=sum(r.precision_at_k for r in query_results) / n,
        recall_at_k=sum(r.recall_at_k for r in query_results) / n,
        avg_relevance=sum(r.avg_relevance for r in query_results) / n,
        avg_latency_ms=sum(r.latency_ms for r in query_results) / n,
        results=query_results,
        generated_at=now,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Markdown report generator
# ─────────────────────────────────────────────────────────────────────────────

def _passage_table(passages: list[dict], keywords: list[str], top_k: int) -> str:
    """Render retrieved passages as a markdown table for the report."""
    rows = ["| Rank | Relevance | Relevant? | Excerpt (first 150 chars) |",
            "|---|---|---|---|"]
    for i, p in enumerate(passages[:top_k], 1):
        rel = p.get("relevance", 0.0)
        is_rel = "✅" if _is_relevant(p["text"], keywords) else "—"
        excerpt = p["text"][:150].replace("|", "\\|").replace("\n", " ")
        rows.append(f"| {i} | {rel:.3f} | {is_rel} | {excerpt}… |")
    return "\n".join(rows)


def generate_markdown_report(report: EvalReport, output_path: Path) -> None:
    """
    Write a comprehensive Markdown evaluation report to output_path.
    Includes aggregate metrics, per-fault passage tables, and interpretation notes.
    """
    lines: list[str] = []

    # Header
    lines += [
        f"# ATHENA RAG — {report.suite_name}",
        "",
        f"> **Generated:** {report.generated_at}  ",
        f"> **Top-K:** {report.top_k}  ",
        f"> **Queries evaluated:** {report.num_queries}  ",
        f"> **Vector store:** ChromaDB (`nasa_hdbk_1002`)  ",
        f"> **Embedding model:** `openai/text-embedding-3-small` via OpenRouter",
        "",
        "---",
        "",
    ]

    # Aggregate metrics table
    lines += [
        "## Aggregate Metrics",
        "",
        "| Metric | Value | Target | Status |",
        "|---|---|---|---|",
        f"| **Hit Rate @{report.top_k}** | {report.hit_rate:.1%} | ≥ 80% | {'✅' if report.hit_rate >= 0.8 else '❌'} |",
        f"| **Precision @{report.top_k}** | {report.precision_at_k:.3f} | ≥ 0.30 | {'✅' if report.precision_at_k >= 0.30 else '❌'} |",
        f"| **Recall @{report.top_k}** | {report.recall_at_k:.3f} | ≥ 0.30 | {'✅' if report.recall_at_k >= 0.30 else '❌'} |",
        f"| **MRR @{report.top_k}** | {report.mrr:.3f} | ≥ 0.70 | {'✅' if report.mrr >= 0.70 else '❌'} |",
        f"| **Avg Relevance** | {report.avg_relevance:.3f} | ≥ 0.40 | {'✅' if report.avg_relevance >= 0.40 else '❌'} |",
        f"| **Avg Latency** | {report.avg_latency_ms:.1f} ms | ≤ 1000 ms | {'✅' if report.avg_latency_ms <= 1000 else '❌'} |",
        "",
        "> **Relevance criterion:** A passage is judged relevant if it contains ≥ 2 of the",
        "> ground-truth keywords for that fault scenario (case-insensitive substring match).",
        "> **Recall denominator:** number of expected relevant handbook sections per fault.",
        "",
        "---",
        "",
    ]

    # Per-query summary table
    lines += [
        "## Per-Fault Summary",
        "",
        f"| Fault | Hit | RR | P@{report.top_k} | R@{report.top_k} | Avg Sim | Latency | Keywords Matched |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in report.results:
        icon = "✅" if r.hit else "❌"
        kw_str = ", ".join(f"`{k}`" for k in r.matched_keywords) if r.matched_keywords else "—"
        lines.append(
            f"| **{r.description}** | {icon} | {r.reciprocal_rank:.2f} "
            f"| {r.precision_at_k:.2f} | {r.recall_at_k:.2f} "
            f"| {r.avg_relevance:.3f} | {r.latency_ms:.0f} ms | {kw_str} |"
        )
    lines += ["", "---", ""]

    # Per-fault detailed sections
    lines.append("## Per-Fault Detailed Results")
    lines.append("")

    for r in report.results:
        icon = "✅ HIT" if r.hit else "❌ MISS"
        lines += [
            f"### {r.description} — `{r.fault_id}` {icon}",
            "",
            f"**Query sent to vectorstore:**",
            f"> {r.query}",
            "",
            f"**Expected relevant handbook sections:** {', '.join(r.relevant_sections)}",
            "",
            f"**Metrics:**",
            "",
            f"| Metric | Value |",
            f"|---|---|",
            f"| Reciprocal Rank | {r.reciprocal_rank:.4f} |",
            f"| Precision@{report.top_k} | {r.precision_at_k:.4f} |",
            f"| Recall@{report.top_k} | {r.recall_at_k:.4f} |",
            f"| Avg Cosine Similarity | {r.avg_relevance:.4f} |",
            f"| Relevant passages in top-{report.top_k} | {r.relevant_count} / {report.top_k} |",
            f"| Retrieval latency | {r.latency_ms:.1f} ms |",
            "",
            f"**Retrieved passages (top-{report.top_k}):**",
            "",
            _passage_table(r.retrieved_passages, r.keywords, report.top_k),
            "",
        ]

        # Interpretation
        if r.hit:
            lines += [
                f"**Interpretation:** Retrieval succeeded. The vectorstore returned at least one",
                f"passage matching the `{r.fault_id}` fault scenario at rank 1/{r.reciprocal_rank:.0f}.",
                f"Keywords matched: {', '.join(f'`{k}`' for k in r.matched_keywords)}.",
            ]
        else:
            lines += [
                f"**Interpretation:** ⚠️ Retrieval missed — no passage contained ≥ 2 required",
                f"keywords for `{r.fault_id}`. Consider adding a dedicated knowledge base entry",
                f"to `seed.py` for this fault scenario.",
            ]
        lines += ["", "---", ""]

    # Notes section
    lines += [
        "## Notes & Next Steps",
        "",
        "- **Synthetic KB:** Results are based on the 18-entry synthetic FDIR knowledge base.",
        "  Ingesting the real NASA-HDBK-1002 PDF will increase vocabulary diversity and",
        "  is expected to improve Avg Relevance above 0.60.",
        "- **Precision denominator:** `K` passages retrieved per query. Low Precision@K with",
        "  high Hit Rate means relevant passages exist but so do off-topic ones.",
        "- **Recall denominator:** number of `relevant_sections` listed per fault (a lower bound).",
        "  Actual recall against a full golden set may differ.",
        "- **RAGAS integration:** For a full RAGAS-framework evaluation (faithfulness, answer",
        "  relevancy, context precision), see the [RAGAS docs](https://docs.ragas.io/).",
        "  The `EvalReport` structure is compatible with RAGAS dataset format.",
        "",
        f"*Report auto-generated by `backend/athena/rag/evaluate.py` — {report.generated_at}*",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Markdown report written → %s", output_path)
    print(f"\n📄 Markdown report saved → {output_path}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Evaluate ATHENA RAG pipeline")
    parser.add_argument("--top-k", type=int, default=4, help="Passages to retrieve per query")
    parser.add_argument("--demo-only", action="store_true",
                        help="Only evaluate the 3 demo-safe faults (tcs, ttc, propulsion)")
    parser.add_argument("--verbose", action="store_true", help="Print retrieved passages to stdout")
    parser.add_argument(
        "--out",
        type=str,
        default=str(Path(__file__).parent / "EVAL_REPORT.md"),
        help="Output path for the Markdown report",
    )
    args = parser.parse_args()

    from backend.athena.rag.pipeline import AthenaRAGPipeline

    rag = AthenaRAGPipeline(top_k=args.top_k)

    if not rag.is_ready():
        print("✗ Vectorstore not built. Run: python -m backend.athena.rag.seed --force-rebuild",
              file=sys.stderr)
        sys.exit(1)

    queries  = DEMO_QUERIES if args.demo_only else EXTENDED_QUERIES
    suite_nm = "Demo Fault Evaluation" if args.demo_only else "Full FDIR Evaluation Suite"

    print(f"Evaluating {len(queries)} queries against '{rag._collection_name}' …\n")
    report = evaluate(rag, queries=queries, top_k=args.top_k, suite_name=suite_nm)

    print(report.summary())

    if args.verbose:
        print("\n── Detailed Passages ──")
        for qr in report.results:
            print(f"\n▸ {qr.description}  (fault_id: {qr.fault_id})")
            print(f"  Query: {qr.query[:100]}…")
            for i, p in enumerate(qr.retrieved_passages[:args.top_k], 1):
                rel_tag = "[RELEVANT]" if _is_relevant(p["text"], qr.keywords) else "         "
                print(f"  [{i}] {rel_tag} sim={p['relevance']:.3f}  {p['text'][:120]}…")

    generate_markdown_report(report, Path(args.out))
