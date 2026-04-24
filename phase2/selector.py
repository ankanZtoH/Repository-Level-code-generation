"""
AI Code Agent — Phase 2: Context Selector (Aider-inspired)
Selects the most relevant files and code snippets for a given task.
Uses LLM-based ranking when needed, with fast heuristic pre-filtering.
"""

from utils.logger import log, separator
from utils.llm import query_llm_json
from utils.file_ops import read_file


def select_context(task: str, repo_analysis: dict, max_files: int = 3) -> list:
    """
    Select the most relevant files for a task.

    Returns list of dicts:
        [{"path": str, "relative": str, "content": str, "reason": str}]
    """
    separator("Context Selection")
    log("INFO", f"Selecting context for: {task}")

    files = repo_analysis.get("files", [])
    if not files:
        log("ERROR", "No files in repo analysis")
        return []

    # Stage 1: Heuristic pre-filter (keyword matching)
    scored = _heuristic_rank(task, files)

    # For small repos (≤10 files), heuristic ranking is sufficient
    # LLM ranking is only used for large repos where selection matters more
    if len(scored) <= max_files or len(files) <= 10:
        selected = scored[:max_files]
    else:
        # Stage 2: LLM-based ranking for top candidates
        candidates = scored[:min(len(scored), max_files * 3)]
        selected = _llm_rank(task, candidates, max_files)

    # Load content for selected files
    result = []
    for item in selected[:max_files]:
        content = read_file(item["path"])
        result.append({
            "path": item["path"],
            "relative": item["relative"],
            "content": content,
            "reason": item.get("reason", "relevant file"),
        })
        log("CONTEXT", f"Selected: {item['relative']} — {item.get('reason', 'relevant')}")

    return result


def _heuristic_rank(task: str, files: list) -> list:
    """
    Fast keyword-based ranking of files against the task.
    """
    task_lower = task.lower()
    task_words = set(task_lower.split())

    scored = []
    for f in files:
        score = 0
        rel = f["relative"].lower()
        lang = f["language"]

        # Filename keyword match
        for word in task_words:
            if word in rel:
                score += 10

        # Language relevance
        if lang in task_lower:
            score += 5

        # Prefer code files over docs
        if lang in ("python", "javascript", "java", "c", "cpp", "html", "css"):
            score += 3

        # Prefer smaller files (more focused)
        if f["size"] < 5000:
            score += 2

        # Function name matching
        for func in f.get("functions", []):
            for word in task_words:
                if word in func["name"].lower():
                    score += 8

        scored.append({**f, "_score": score})

    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored


def _llm_rank(task: str, candidates: list, max_files: int) -> list:
    """
    Use LLM to rank candidate files by relevance to the task.
    """
    file_list = "\n".join(
        f"  {i+1}. {c['relative']} ({c['language']}, {c['size']}B)"
        + (f" — functions: {', '.join(fn['name'] for fn in c.get('functions', [])[:5])}" if c.get("functions") else "")
        for i, c in enumerate(candidates)
    )

    prompt = f"""Given this task: "{task}"

Which of these files are most relevant? Pick up to {max_files}.

Files:
{file_list}

Return JSON: {{"selections": [{{"index": 1, "reason": "..."}}]}}"""

    result = query_llm_json(prompt)
    selections = result.get("selections", [])

    if not selections:
        # Fallback to heuristic top-N
        return candidates[:max_files]

    ranked = []
    for sel in selections:
        idx = sel.get("index", 0) - 1
        if 0 <= idx < len(candidates):
            candidates[idx]["reason"] = sel.get("reason", "LLM selected")
            ranked.append(candidates[idx])

    return ranked if ranked else candidates[:max_files]


def build_context_prompt(context_files: list) -> str:
    """Build a context string from selected files for LLM prompts."""
    parts = []
    for cf in context_files:
        parts.append(f"### {cf['relative']}\n```\n{cf['content']}\n```")
    return "\n\n".join(parts)
