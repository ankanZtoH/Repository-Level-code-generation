"""
AI Code Agent — Semantic Code Retrieval
Indexes code at function level using sentence-transformers embeddings.
Stored purely in memory (no vector DB required).

Usage:
    from phase2.retrieval import index_repo, query_relevant_code

    index_repo(repo_analysis)          # call once after analyze_repo()
    results = query_relevant_code(task, top_k=3)
"""

import os
import math
import logging
from utils.file_ops import read_file

logger = logging.getLogger(__name__)

# ─── In-memory index ────────────────────────────────────────
# Each entry: {"path": str, "relative": str, "name": str, "content": str, "embedding": list[float]}
_INDEX: list = []
_MODEL = None


# ─── Public API ─────────────────────────────────────────────

def index_repo(repo_analysis: dict) -> int:
    """
    Build the in-memory semantic index from a repo_analysis dict
    (output of analyzer.analyze_repo).

    Chunks at function level. Falls back to whole-file chunks for
    non-Python files or files with no detected functions.

    Returns the number of chunks indexed.
    """
    global _INDEX
    _INDEX = []

    model = _get_model()
    if model is None:
        logger.warning("sentence-transformers not available — retrieval disabled")
        return 0

    chunks = _extract_chunks(repo_analysis)
    if not chunks:
        return 0

    texts = [c["content"] for c in chunks]
    embeddings = _encode(model, texts)

    for chunk, emb in zip(chunks, embeddings):
        _INDEX.append({**chunk, "embedding": emb})

    logger.info(f"Indexed {len(_INDEX)} chunks from {repo_analysis.get('path', '?')}")
    return len(_INDEX)


def query_relevant_code(task: str, top_k: int = 3) -> list:
    """
    Return the top_k most relevant code chunks for the given task string.

    Returns:
        [
            {
                "path":     str,   # absolute path
                "relative": str,   # repo-relative path
                "name":     str,   # function/file name
                "content":  str,   # source text of the chunk
                "score":    float, # cosine similarity in [0, 1]
            },
            ...
        ]
    Returns [] if the index is empty or the model failed to load.
    """
    if not _INDEX:
        logger.warning("Index is empty — call index_repo() first")
        return []

    model = _get_model()
    if model is None:
        return []

    query_emb = _encode(model, [task])[0]
    scored = [
        (chunk, _cosine(query_emb, chunk["embedding"]))
        for chunk in _INDEX
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    return [
        {
            "path":     chunk["path"],
            "relative": chunk["relative"],
            "name":     chunk["name"],
            "content":  chunk["content"],
            "score":    round(score, 4),
        }
        for chunk, score in scored[:top_k]
    ]


# ─── Chunking ────────────────────────────────────────────────

def _extract_chunks(repo_analysis: dict) -> list:
    """
    Produce a flat list of text chunks from repo_analysis.

    Strategy:
    - Python files → one chunk per function (name + source lines)
    - All other files / files with no functions → one chunk = whole file
      (capped at 300 lines to keep embeddings meaningful)
    """
    chunks = []
    repo_root = repo_analysis.get("path", "")

    for fi in repo_analysis.get("files", []):
        path = fi["path"]
        relative = fi["relative"]
        language = fi["language"]
        functions = fi.get("functions", [])

        # Skip non-code files
        if language in ("unknown", "markdown", "text", "json", "xml", "yaml"):
            continue

        source = read_file(path)
        if not source:
            continue

        source_lines = source.splitlines()

        if language == "python" and functions:
            for func in functions:
                start = func["lineno"] - 1           # 0-indexed
                end = func.get("end_lineno", func["lineno"])
                snippet = "\n".join(source_lines[start:end])
                # Prepend path context so embeddings encode location meaning
                header = f"# {relative} — def {func['name']}"
                chunks.append({
                    "path":     path,
                    "relative": relative,
                    "name":     func["name"],
                    "content":  f"{header}\n{snippet}",
                })
        else:
            # Whole-file chunk (capped)
            MAX_LINES = 300
            capped = "\n".join(source_lines[:MAX_LINES])
            header = f"# {relative}"
            chunks.append({
                "path":     path,
                "relative": relative,
                "name":     os.path.basename(relative),
                "content":  f"{header}\n{capped}",
            })

    return chunks


# ─── Embedding ───────────────────────────────────────────────

# def _get_model():
#     """
#     Lazy-load the sentence-transformers model.
#     Uses all-MiniLM-L6-v2: 80MB, fast, good at code similarity.
#     Returns None if sentence-transformers is not installed.
#     """
#     global _MODEL
#     if _MODEL is not None:
#         return _MODEL

#     try:
#         # from sentence_transformers import SentenceTransformer
#         from sentence_transformers import SentenceTransformer
#         _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
#         logger.info("Loaded embedding model: all-MiniLM-L6-v2")
#     except ImportError:
#         logger.warning(
#             "sentence-transformers not installed. "
#             "Run: pip install sentence-transformers"
#         )
#         _MODEL = None
#     except Exception as e:
#         logger.warning(f"Failed to load embedding model: {e}")
#         _MODEL = None

#     return _MODEL


_MODEL = None

def _get_model():
    global _MODEL

    if _MODEL is not None:
        return _MODEL

    try:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        print("Loaded embedding model: all-MiniLM-L6-v2")

    except ImportError:
        print("ERROR: sentence-transformers not installed.")
        print("Run: pip install sentence-transformers")
        return None

    except Exception as e:
        print(f"ERROR: Failed to load embedding model: {e}")
        return None

    return _MODEL


def _encode(model, texts: list) -> list:
    """
    Encode a list of strings into normalized float embeddings.
    Returns list of list[float].
    """
    try:
        embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        # Normalize to unit vectors so cosine sim = dot product
        return [_normalize(emb.tolist()) for emb in embeddings]
    except Exception as e:
        logger.error(f"Encoding failed: {e}")
        return [[0.0] * 384] * len(texts)   # all-MiniLM-L6-v2 dim = 384


# ─── Math ────────────────────────────────────────────────────

def _normalize(vec: list) -> list:
    """L2-normalize a vector."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


def _cosine(a: list, b: list) -> float:
    """
    Cosine similarity between two pre-normalized vectors.
    Equivalent to dot product when both are unit vectors.
    """
    return sum(x * y for x, y in zip(a, b))