"""
AI Code Agent — Phase 2: Context Selector
Selects the most relevant files for a given task.
Supports ALL languages — uses keyword heuristic ranking.
"""

from utils.logger import log, separator
from utils.file_ops import read_file


# Language groups for scoring
_CODE_LANGUAGES = {
    "python", "javascript", "typescript", "java",
    "c", "cpp", "ruby", "go", "rust", "bash",
}

_WEB_LANGUAGES = {"html", "css", "javascript", "typescript"}


def select_context(task: str, repo_analysis: dict, max_files: int = 3,
                    retrieval_results: list = None,
                    recently_edited: list = None) -> list:
    """
    Select the most relevant files for a task.
    Combines heuristic ranking with retrieval scores when available.
    Boosts recently edited files for continuity.

    Args:
        recently_edited: list of relative paths recently modified by the agent

    Returns list of dicts:
        [{"path": str, "relative": str, "content": str, "reason": str}]
    """
    separator("Context Selection")
    log("INFO", f"Selecting context for: {task}")

    files = repo_analysis.get("files", [])
    if not files:
        log("ERROR", "No files in repo analysis")
        return []

    # Rank by heuristic score
    scored = _heuristic_rank(task, files)

    # Merge retrieval scores if available
    if retrieval_results:
        scored = _merge_retrieval_scores(scored, retrieval_results)

    # Boost recently edited files (Problem 7: recency weighting)
    if recently_edited:
        scored = _boost_recently_edited(scored, recently_edited)

    selected = scored[:max_files]

    # Load content for selected files
    result = []
    for item in selected:
        content = read_file(item["path"])
        if content:
            reason = f"score={item['_score']}, {item['language']}"
            log("CONTEXT", f"Selected: {item['relative']} ({reason})")
            result.append({
                "path": item["path"],
                "relative": item["relative"],
                "content": content,
                "language": item["language"],
                "reason": reason,
            })

    return result


def _heuristic_rank(task: str, files: list) -> list:
    """
    Fast keyword-based ranking of files against the task.
    Prefers: filename match > function match > language match > smaller files.
    """
    task_lower = task.lower()
    task_words = set(task_lower.split())

    scored = []
    for f in files:
        score = 0
        rel = f["relative"].lower()
        lang = f.get("language", "unknown")

        # Filename keyword match (strongest signal)
        for word in task_words:
            if len(word) > 2 and word in rel:
                score += 10

        # Language name match in task
        if lang in task_lower:
            score += 7

        # Syntax error boosting (highest priority)
        if f.get("has_syntax_error"):
            score += 50
            log("CONTEXT", f"Boosting {f['relative']} due to detected syntax error")

        # Web keywords → prefer web files
        web_words = {"html", "css", "web", "page", "style", "website", "frontend", "ui"}
        if web_words & task_words and lang in _WEB_LANGUAGES:
            score += 6

        # Function name matching (Python only — others don't have AST data)
        for func in f.get("functions", []):
            for word in task_words:
                if len(word) > 2 and word in func["name"].lower():
                    score += 8

        # Class name matching
        for cls in f.get("classes", []):
            for word in task_words:
                if len(word) > 2 and word in cls["name"].lower():
                    score += 6

        # Prefer code files over docs
        if lang in _CODE_LANGUAGES or lang in _WEB_LANGUAGES:
            score += 2

        # Prefer smaller files (more focused, easier for LLM)
        if f["size"] < 2000:
            score += 4
        elif f["size"] < 5000:
            score += 2

        # Slight boost for files with functions
        if f.get("functions"):
            score += 1

        scored.append({**f, "_score": score})

    scored.sort(key=lambda x: (-x["_score"], x["size"]))
    return scored


def _merge_retrieval_scores(scored: list, retrieval_results: list) -> list:
    """
    Boost heuristic scores for files that also appear in retrieval results.
    Retrieval score (0-1) is scaled to 0-15 bonus points.
    """
    if not retrieval_results:
        return scored

    # Build lookup: relative_path -> retrieval score
    retrieval_map = {}
    for r in retrieval_results:
        rel = r.get("relative", "")
        score = r.get("score", 0)
        # A file may appear multiple times (multiple chunks) — keep highest
        if rel not in retrieval_map or score > retrieval_map[rel]:
            retrieval_map[rel] = score

    for item in scored:
        rel = item.get("relative", "")
        if rel in retrieval_map:
            bonus = int(retrieval_map[rel] * 15)
            item["_score"] += bonus
            log("CONTEXT", f"Retrieval boost: {rel} +{bonus} (similarity={retrieval_map[rel]:.3f})")

    scored.sort(key=lambda x: (-x["_score"], x["size"]))
    return scored


def _boost_recently_edited(scored: list, recently_edited: list) -> list:
    """
    Boost score for files recently modified by the agent.
    Ensures continuity — the agent revisits files it already touched.
    """
    if not recently_edited:
        return scored

    edited_set = set(recently_edited)
    for item in scored:
        rel = item.get("relative", "")
        if rel in edited_set:
            bonus = 12
            item["_score"] += bonus
            log("CONTEXT", f"Recency boost: {rel} +{bonus} (recently edited)")

    scored.sort(key=lambda x: (-x["_score"], x["size"]))
    return scored


def build_context_prompt(context_files: list) -> str:
    """Build a compact context string from selected files for LLM prompts."""
    lang_fence = {
        "python": "python", "javascript": "javascript", "java": "java",
        "c": "c", "cpp": "cpp", "html": "html", "css": "css",
        "typescript": "typescript", "ruby": "ruby", "bash": "bash",
    }

    parts = []
    for cf in context_files:
        lang = cf.get("language", "")
        fence = lang_fence.get(lang, "")
        parts.append(f"### {cf['relative']}\n```{fence}\n{cf['content']}\n```")
    return "\n\n".join(parts)