"""
AERO-ASTRA — ATHENA RAG: Core Pipeline
=======================================
Implements the Retrieval-Augmented Generation pipeline that enriches
ATHENA's recovery plans with authoritative FDIR guidance from
NASA-HDBK-1002 (Fault Management Handbook).

Architecture:
    1. Ingest     — Parse NASA-HDBK-1002.pdf with PyMuPDF (fitz) for high-fidelity
                    text extraction, preserving paragraph structure and page metadata.
    2. Chunk      — Split with LangChain RecursiveCharacterTextSplitter:
                    chunk_size=1000 chars, overlap=200 chars. The splitter tries
                    to break on paragraph (\n\n), line (\n), sentence ('. '),
                    and word boundaries in that order — preserving complex systems
                    engineering context across chunk boundaries.
    3. Embed      — Embed chunks using OpenAI text-embedding-3-small via OpenRouter
    4. Store      — Persist embeddings in a local ChromaDB collection
    5. Retrieve   — Query top-k relevant passages for a given fault context
    6. Augment    — Return formatted context string ready for ATHENA's prompt

Usage:
    # First-time setup (downloads PDF if missing, builds vectorstore):
    python -m backend.athena.rag.pipeline --build

    # Query existing vectorstore:
    from backend.athena.rag.pipeline import AthenaRAGPipeline
    rag = AthenaRAGPipeline()
    context = rag.retrieve("battery degradation recovery thermal runaway")
    print(context)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import chromadb

# PyMuPDF is the primary PDF parser — far superior to pypdf for
# scanned/complex PDFs (handles embedded fonts, tables, multi-column).
# Falls back to pypdf if fitz is not installed.
try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred import
    _PYMUPDF_AVAILABLE = True
except ImportError:
    try:
        import fitz  # older PyMuPDF (< 1.24)
        _PYMUPDF_AVAILABLE = True
    except ImportError:
        _PYMUPDF_AVAILABLE = False
        from pypdf import PdfReader  # fallback

from langchain_text_splitters import RecursiveCharacterTextSplitter

log = logging.getLogger("athena.rag.pipeline")

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

_RAG_DIR      = Path(__file__).resolve().parent
DATA_DIR      = _RAG_DIR / "data"
VECTORSTORE_DIR = _RAG_DIR / "vectorstore"
PDF_PATH      = DATA_DIR / "NASA-HDBK-1002.pdf"

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

COLLECTION_NAME   = "nasa_hdbk_1002"
# Recursive character splitter settings — 1000 chars / 200 char overlap.
# This size is chosen to fit ~600-800 tokens (well within the 8192-token
# context limit of text-embedding-3-small) while preserving enough
# surrounding context for accurate cosine similarity matching.
CHUNK_SIZE        = 1000    # characters
CHUNK_OVERLAP     = 200     # characters shared between adjacent chunks
TOP_K             = 4        # passages to retrieve per query
EMBED_MODEL       = "models/gemini-embedding-001"  # Google AI Studio OpenAI-compat ID
GEMINI_EMBED_URL  = "https://generativelanguage.googleapis.com/v1beta/openai/"


# Separators for RecursiveCharacterTextSplitter, in priority order:
# paragraph break → line break → sentence end → word boundary → characters
_SPLIT_SEPARATORS = ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " ", ""]

# Build manifest — persisted JSON sidecar that records the parameters used
# to build the current vectorstore. On startup, AthenaRAGPipeline compares
# the current config against the manifest; if they match, build() is a no-op.
# This prevents redundant embedding API calls every time the server restarts.
MANIFEST_PATH     = VECTORSTORE_DIR / "build_manifest.json"


# ─────────────────────────────────────────────────────────────────────────────
# Text chunking — RecursiveCharacterTextSplitter
# ─────────────────────────────────────────────────────────────────────────────

def _chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """
    Split text into overlapping character-level chunks using LangChain's
    RecursiveCharacterTextSplitter.

    The splitter tries separators in priority order:
        \\n\\n  →  \\n  →  '. '  →  ', '  →  ' '  →  '' (character)
    This ensures natural paragraph and sentence boundaries are preserved
    over hard character cuts — critical for retaining engineering context
    (e.g., a numbered procedure list is not split mid-step).

    Args:
        text:       Raw text to split.
        chunk_size: Target chunk length in characters (default 1000).
        overlap:    Overlap in characters between consecutive chunks (default 200).

    Returns:
        List of non-empty chunk strings.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=_SPLIT_SEPARATORS,
        length_function=len,
        is_separator_regex=False,
    )
    raw_chunks = splitter.split_text(text)
    # Filter blanks and strip whitespace
    return [c.strip() for c in raw_chunks if c.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# PDF extraction — PyMuPDF (primary) / pypdf (fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_pdf_text_pymupdf(pdf_path: Path) -> str:
    """
    Extract text from a PDF using PyMuPDF (fitz).

    PyMuPDF advantages over pypdf:
    - Handles complex font encodings and embedded CMap tables.
    - Extracts text in reading order (left-right, top-bottom) per page.
    - Preserves paragraph breaks via block-level extraction.
    - Correctly handles hyphenation at line breaks.
    """
    doc = fitz.open(str(pdf_path))
    pages_text: list[str] = []
    for page_num, page in enumerate(doc):
        try:
            # Extract as plain text, respecting reading order
            # 'text' mode returns words in correct reading order
            page_text = page.get_text("text")  # type: ignore[arg-type]
            if page_text and page_text.strip():
                pages_text.append(page_text)
        except Exception as exc:
            log.warning("PyMuPDF: could not extract page %d: %s", page_num, exc)
    doc.close()
    full_text = "\n\n".join(pages_text)  # double newline between pages = paragraph break
    log.info(
        "PyMuPDF extracted %d chars from %d pages",
        len(full_text),
        len(pages_text),
    )
    return full_text


def _extract_pdf_text_pypdf(pdf_path: Path) -> str:
    """Fallback: extract text using pypdf (less robust than PyMuPDF)."""
    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
        except Exception as exc:
            log.warning("pypdf: could not extract page %d: %s", i, exc)
    full_text = "\n\n".join(pages)
    log.info("pypdf extracted %d chars from %d pages", len(full_text), len(reader.pages))
    return full_text


def _extract_pdf_text(pdf_path: Path) -> str:
    """
    Extract all text from a PDF, preferring PyMuPDF over pypdf.
    Automatically falls back if PyMuPDF is not installed.
    """
    log.info(
        "Extracting text from %s using %s …",
        pdf_path.name,
        "PyMuPDF" if _PYMUPDF_AVAILABLE else "pypdf (fallback)",
    )
    if _PYMUPDF_AVAILABLE:
        return _extract_pdf_text_pymupdf(pdf_path)
    return _extract_pdf_text_pypdf(pdf_path)


# ─────────────────────────────────────────────────────────────────────────────
# Build manifest helpers
# ─────────────────────────────────────────────────────────────────────────────

def _current_config() -> dict:
    """Return a dict of the parameters that define the current build config."""
    return {
        "embed_model":   EMBED_MODEL,
        "chunk_size":    CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "collection":    COLLECTION_NAME,
    }


def _load_manifest(path: Path = MANIFEST_PATH) -> dict | None:
    """
    Load and return the JSON build manifest, or None if it doesn't exist
    or is unreadable.
    """
    if not path.exists():
        return None
    try:
        import json
        return json.loads(path.read_text())
    except Exception as exc:
        log.warning("Could not read build manifest at %s: %s", path, exc)
        return None


def _save_manifest(doc_count: int, path: Path = MANIFEST_PATH) -> None:
    """Write the current build config + doc count to the manifest file."""
    import json, datetime
    manifest = {
        **_current_config(),
        "doc_count":  doc_count,
        "built_at":   datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2))
    log.info("Build manifest written → %s", path)


def _manifest_matches_current_config(manifest: dict) -> bool:
    """
    Return True if the persisted manifest matches the active configuration.
    If any build parameter changed (model, chunk size, overlap), returns False
    so build() re-embeds with the new config.
    """
    cfg = _current_config()
    return all(manifest.get(k) == v for k, v in cfg.items())


# ─────────────────────────────────────────────────────────────────────────────
# Embedding via OpenRouter
# ─────────────────────────────────────────────────────────────────────────────

class GeminiEmbedder:
    """
    Thin wrapper around Google AI Studio's embedding endpoint using the
    openai-compatible Python client. Uses text-embedding-004 by default.
    Falls back to OPENROUTER_API_KEY for backwards compatibility.
    """

    def __init__(self, model: str = EMBED_MODEL):
        # GEMINI_API_KEY preferred; fall back to OPENROUTER_API_KEY for compat
        api_key = (
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
        )
        if not api_key:
            raise EnvironmentError(
                "API key not found. Set GEMINI_API_KEY (Google AI Studio) "
                "or OPENROUTER_API_KEY in environment."
            )
        from openai import OpenAI
        self._client = OpenAI(
            api_key=api_key,
            base_url=GEMINI_EMBED_URL,
        )
        self.model = model
        log.info("GeminiEmbedder ready | model=%s", model)


    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of strings, returning a list of float vectors.
        Sends in batches of 100 to stay within API limits.
        """
        all_embeddings: list[list[float]] = []
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            log.debug("Embedding batch %d-%d of %d …", i, i + len(batch), len(texts))
            resp = self._client.embeddings.create(model=self.model, input=batch)
            all_embeddings.extend([item.embedding for item in resp.data])
        return all_embeddings


# ─────────────────────────────────────────────────────────────────────────────
# AthenaRAGPipeline
# ─────────────────────────────────────────────────────────────────────────────

class AthenaRAGPipeline:
    """
    Core RAG pipeline for ATHENA.

    Lifecycle:
        # Recommended: use the module-level singleton via get_pipeline()
        rag = get_pipeline()          # returns cached instance, auto-seeds
        context = rag.retrieve("thermal runaway EPS recovery")

        # Or manage lifecycle manually:
        rag = AthenaRAGPipeline()
        rag.build()                   # first run only — skipped on subsequent calls
        context = rag.retrieve("battery degradation recovery")

    Idempotency contract:
        build() is a guaranteed no-op if:
        - The ChromaDB collection already contains documents, AND
        - The build manifest reports the same embed_model, chunk_size,
          chunk_overlap, and collection_name as the current config.
        Only a parameter change or force_rebuild=True triggers re-embedding.

    The retrieve() method returns a formatted markdown string ready to be
    injected directly into ATHENA's system or user prompt.
    """

    def __init__(
        self,
        top_k: int = TOP_K,
        vectorstore_dir: Path = VECTORSTORE_DIR,
        collection_name: str = COLLECTION_NAME,
    ):
        self.top_k = top_k
        self._chroma_client = chromadb.PersistentClient(path=str(vectorstore_dir))
        self._collection_name = collection_name
        self._collection: chromadb.Collection | None = None
        self._embedder: GeminiEmbedder | None = None

        # Try to connect to an already-built collection (no API key needed for reads
        # if we store embeddings — ChromaDB handles similarity search locally)
        existing = [c.name for c in self._chroma_client.list_collections()]
        if collection_name in existing:
            self._collection = self._chroma_client.get_collection(collection_name)
            log.info(
                "RAG vectorstore loaded | collection=%s | docs=%d",
                collection_name,
                self._collection.count(),
            )
        else:
            log.info(
                "RAG vectorstore not found (%s). Call .build() to ingest the handbook.",
                collection_name,
            )

    def _get_embedder(self) -> GeminiEmbedder:
        """Lazy-initialise the embedder — never created until first embed call."""
        if self._embedder is None:
            self._embedder = GeminiEmbedder()
        return self._embedder

    def is_ready(self) -> bool:
        """
        Return True if the vectorstore is populated AND the manifest confirms
        the embeddings were built with the current configuration.

        A mismatch (e.g. chunk_size changed) returns False so the caller
        knows a rebuild is required.
        """
        if self._collection is None or self._collection.count() == 0:
            return False
        manifest = _load_manifest()
        if manifest is None:
            # No manifest means the vectorstore was built by seed.py or an
            # older pipeline version. Accept it as-is (don't force rebuild).
            return True
        return _manifest_matches_current_config(manifest)

    def ensure_ready(self, auto_seed: bool = True) -> bool:
        """
        Guarantee the vectorstore is populated before ATHENA uses it.

        Behaviour:
            1. If already ready (populated + manifest matches) — no-op, return True.
            2. If not ready and auto_seed=True — seed from the synthetic FDIR
               knowledge base (seed.py) without requiring the PDF or API key check.
               Returns True on success, False on failure.
            3. If auto_seed=False — return False immediately (caller must call build()).

        This is the recommended entry point for ATHENA's runtime startup:

            rag = get_pipeline()
            if not rag.ensure_ready():
                log.warning("RAG context unavailable")
        """
        if self.is_ready():
            log.debug("RAG vectorstore already ready (%d docs).", self._collection.count())  # type: ignore[union-attr]
            return True

        if not auto_seed:
            log.warning("RAG not ready and auto_seed=False. Call .build() or .ensure_ready().")
            return False

        log.info("RAG vectorstore empty or stale — auto-seeding from FDIR knowledge base …")
        try:
            from backend.athena.rag.seed import seed
            seed(force_rebuild=True)
            # Reload the collection reference after seeding
            existing = [c.name for c in self._chroma_client.list_collections()]
            if self._collection_name in existing:
                self._collection = self._chroma_client.get_collection(self._collection_name)
            return self.is_ready()
        except Exception as exc:
            log.error("RAG auto-seed failed: %s", exc)
            return False

    def build(self, pdf_path: Path = PDF_PATH, force_rebuild: bool = False) -> None:
        """
        Ingest the NASA-HDBK-1002 PDF into ChromaDB.

        Idempotency: this method is a no-op if the collection is already
        populated AND the build manifest confirms the current config matches
        (same embed_model, chunk_size, chunk_overlap). Re-embedding is only
        triggered when:
          - The collection is empty, OR
          - force_rebuild=True, OR
          - A build parameter has changed since the last build.

        Steps:
            1. Check manifest + collection — skip if already up-to-date
            2. Download PDF if missing
            3. Extract text with PyMuPDF (falls back to pypdf)
            4. Chunk with RecursiveCharacterTextSplitter (1000c / 200c overlap)
            5. Embed via OpenRouter text-embedding-3-small
            6. Upsert into ChromaDB
            7. Write build manifest

        Args:
            pdf_path:      Path to the PDF (default: data/NASA-HDBK-1002.pdf)
            force_rebuild: Drop and recreate the collection from scratch.
        """
        # ── Idempotency gate: skip if already built with current config ───────────
        if not force_rebuild:
            existing_names = [c.name for c in self._chroma_client.list_collections()]
            if self._collection_name in existing_names:
                col = self._chroma_client.get_collection(self._collection_name)
                if col.count() > 0:
                    manifest = _load_manifest()
                    if manifest is None or _manifest_matches_current_config(manifest):
                        log.info(
                            "Vectorstore already built (%d docs, config unchanged) — skipping. "
                            "Use force_rebuild=True to re-embed.",
                            col.count(),
                        )
                        self._collection = col
                        return
                    else:
                        log.info(
                            "Build config changed (embed_model / chunk params) — rebuilding vectorstore."
                        )

        # ── 1. Ensure PDF is on disk ───────────────────────────────────────────────
        if not pdf_path.exists():
            from backend.athena.rag.download import ensure_handbook
            pdf_path = ensure_handbook()

        # ── Drop + recreate if forced ───────────────────────────────────────────────
        existing_names = [c.name for c in self._chroma_client.list_collections()]
        if force_rebuild and self._collection_name in existing_names:
            log.info("force_rebuild=True — dropping existing collection '%s'", self._collection_name)
            self._chroma_client.delete_collection(self._collection_name)

        self._collection = self._chroma_client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        # ── 2. Extract text ─────────────────────────────────────────────────────
        raw_text = _extract_pdf_text(pdf_path)

        # ── 3. Chunk ───────────────────────────────────────────────────────────
        chunks = _chunk_text(raw_text)
        log.info("Created %d chunks from %s", len(chunks), pdf_path.name)

        # ── 4. Embed (calls OpenRouter API — only reaches here on first/forced build) ─
        embedder = self._get_embedder()
        log.info(
            "Embedding %d chunks via %s (first build — subsequent startups skip this) …",
            len(chunks),
            EMBED_MODEL,
        )
        vectors = embedder.embed(chunks)

        # ── 5. Upsert into ChromaDB ───────────────────────────────────────────────
        self._collection.upsert(
            ids=[f"chunk_{i}" for i in range(len(chunks))],
            documents=chunks,
            embeddings=vectors,
            metadatas=[
                {
                    "source": "NASA-HDBK-1002",
                    "chunk_index": i,
                    "chunk_size": CHUNK_SIZE,
                    "chunk_overlap": CHUNK_OVERLAP,
                    "embed_model": EMBED_MODEL,
                }
                for i in range(len(chunks))
            ],
        )

        # ── 6. Write build manifest ───────────────────────────────────────────────
        _save_manifest(doc_count=self._collection.count())
        log.info(
            "Build complete | collection=%s | total_docs=%d",
            self._collection_name,
            self._collection.count(),
        )

    def retrieve(self, query: str) -> str:
        """
        Retrieve top-k relevant passages for *query* and return a formatted
        markdown string suitable for injection into ATHENA's LLM prompt.

        Returns an empty string if the vectorstore is not built.
        """
        if not self.is_ready():
            log.warning("RAG vectorstore not built — returning empty context. Call .build() first.")
            return ""

        # Embed the query
        embedder = self._get_embedder()
        query_vector = embedder.embed([query])[0]

        # Search ChromaDB
        results = self._collection.query(
            query_embeddings=[query_vector],
            n_results=min(self.top_k, self._collection.count()),
            include=["documents", "distances"],
        )

        passages = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]

        if not passages:
            return ""

        # Format as a clean block for ATHENA's prompt
        lines = [
            "## NASA-HDBK-1002 Relevant FDIR Guidance",
            "",
            "_The following excerpts are retrieved from the NASA Fault Management Handbook "
            "and represent authoritative FDIR preventive measures applicable to the current fault scenario._",
            "",
        ]
        for i, (passage, dist) in enumerate(zip(passages, distances), 1):
            relevance = max(0.0, 1.0 - dist)
            lines.append(f"### Passage {i}  _(relevance: {relevance:.2f})_")
            lines.append("")
            lines.append(passage.strip())
            lines.append("")

        return "\n".join(lines)

    def retrieve_raw(self, query: str) -> list[dict[str, Any]]:
        """
        Return raw retrieval results as a list of dicts (for evaluation/debugging).
        Each dict has: text, chunk_index, distance, relevance.
        """
        if not self.is_ready():
            return []

        embedder = self._get_embedder()
        query_vector = embedder.embed([query])[0]

        results = self._collection.query(
            query_embeddings=[query_vector],
            n_results=min(self.top_k, self._collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        passages  = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        return [
            {
                "text": doc,
                "chunk_index": meta.get("chunk_index"),
                "distance": dist,
                "relevance": max(0.0, 1.0 - dist),
            }
            for doc, meta, dist in zip(passages, metadatas, distances)
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton — shared across all ATHENA calls
# ─────────────────────────────────────────────────────────────────────────────

_pipeline_singleton: AthenaRAGPipeline | None = None


def get_pipeline(
    top_k: int = TOP_K,
    vectorstore_dir: Path = VECTORSTORE_DIR,
    collection_name: str = COLLECTION_NAME,
) -> AthenaRAGPipeline:
    """
    Return the shared, module-level AthenaRAGPipeline instance.

    On the first call, the instance is created and connects to the persisted
    ChromaDB collection (no embedding API call is made here — only a local
    filesystem read). Subsequent calls return the cached instance immediately.

    This prevents ATHENA from opening multiple ChromaDB connections or
    creating duplicate embedder clients during concurrent planning calls.

    Usage (recommended in ATHENA agent):
        from backend.athena.rag.pipeline import get_pipeline

        rag = get_pipeline()
        if rag.ensure_ready():
            context = rag.retrieve(query)
    """
    global _pipeline_singleton
    if _pipeline_singleton is None:
        log.debug("Initialising AthenaRAGPipeline singleton …")
        _pipeline_singleton = AthenaRAGPipeline(
            top_k=top_k,
            vectorstore_dir=vectorstore_dir,
            collection_name=collection_name,
        )
    return _pipeline_singleton


def reset_pipeline_singleton() -> None:
    """
    Clear the singleton — useful in tests to force a fresh instance.
    Not intended for production use.
    """
    global _pipeline_singleton
    _pipeline_singleton = None


# ─────────────────────────────────────────────────────────────────────────────
# CLI entrypoint
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="ATHENA RAG Pipeline")
    parser.add_argument("--build", action="store_true", help="Build/rebuild the vectorstore from the PDF")
    parser.add_argument("--force-rebuild", action="store_true", help="Drop and recreate collection")
    parser.add_argument("--query", type=str, default=None, help="Test query to retrieve passages for")
    args = parser.parse_args()

    rag = AthenaRAGPipeline()

    if args.build or args.force_rebuild:
        rag.build(force_rebuild=args.force_rebuild)
        print(f"\n✓ Vectorstore built | {rag._collection.count()} chunks indexed")

    if args.query:
        print(f"\n── Retrieving for: '{args.query}' ──\n")
        context = rag.retrieve(args.query)
        print(context if context else "(no results — has the vectorstore been built?)")

    if not args.build and not args.force_rebuild and not args.query:
        print("Usage: python -m backend.athena.rag.pipeline --build [--force-rebuild] [--query <text>]")
        sys.exit(0)
