"""
AI Code Agent — Safe Partial File Editing
Adapted from aider's SEARCH/REPLACE block approach.

Instead of overwriting entire files, applies targeted edits:
  1. Read current content
  2. Find the SEARCH block (exact or fuzzy match)
  3. Replace with the REPLACE block
  4. Validate result before writing

This preserves untouched code, imports, and structure.
"""

import os
import difflib
from difflib import SequenceMatcher
from utils.logger import log
from utils.validator import validate_syntax


def apply_search_replace(content: str, search_block: str, replace_block: str) -> str:
    """
    Apply a single SEARCH/REPLACE edit to file content.
    Tries exact match first, then whitespace-flexible match.

    Returns:
        Updated content string, or empty string on failure.
    """
    if not content or not search_block:
        return ""

    # Normalize line endings
    content = content.replace("\r\n", "\n")
    search_block = search_block.replace("\r\n", "\n")
    replace_block = replace_block.replace("\r\n", "\n")

    # Strategy 1: Exact match
    if search_block in content:
        return content.replace(search_block, replace_block, 1)

    # Strategy 2: Strip trailing whitespace per line and retry
    content_stripped = _strip_trailing_ws(content)
    search_stripped = _strip_trailing_ws(search_block)
    if search_stripped in content_stripped:
        # Find the position in the stripped version, apply to original
        idx = content_stripped.find(search_stripped)
        # Map back to original content by counting lines
        return _apply_at_line_position(content, search_block, replace_block)

    # Strategy 3: Fuzzy match with leading whitespace flexibility
    result = _replace_with_flexible_whitespace(content, search_block, replace_block)
    if result:
        return result

    # Strategy 4: Best-effort similarity match
    result = _replace_most_similar(content, search_block, replace_block)
    if result:
        return result

    return ""


def patch_file(filepath: str, edits: list) -> tuple:
    """
    Apply a list of search/replace edits to a file.

    Args:
        filepath: absolute path to the file
        edits: list of {"search": str, "replace": str} dicts

    Returns:
        (success: bool, message: str)
    """
    if not os.path.isfile(filepath):
        return False, f"File not found: {filepath}"

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return False, f"Cannot read {filepath}: {e}"

    original_content = content
    applied = 0
    failed = []

    for i, edit in enumerate(edits):
        search = edit.get("search", "")
        replace = edit.get("replace", "")

        if not search and not replace:
            continue

        # Empty search = append to file
        if not search:
            content = content + replace
            applied += 1
            continue

        result = apply_search_replace(content, search, replace)
        if result:
            content = result
            applied += 1
        else:
            failed.append(i)
            log("ERROR", f"Edit {i+1} failed: could not find search block")

    if applied == 0 and failed:
        return False, f"All {len(failed)} edits failed to match"

    # Validate before writing
    valid, err = validate_syntax(content, filepath)
    if not valid:
        log("ERROR", f"Syntax validation failed after edit: {err}")
        return False, f"Edit produced invalid syntax: {err}"

    # Write the result
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return False, f"Write failed: {e}"

    msg = f"Applied {applied}/{applied + len(failed)} edits"
    if failed:
        msg += f" ({len(failed)} failed)"
    log("TOOL", f"Patched {filepath}: {msg}")
    return True, msg


# ─── Internal Helpers ───────────────────────────────────────

def _strip_trailing_ws(text: str) -> str:
    """Strip trailing whitespace from each line."""
    return "\n".join(line.rstrip() for line in text.split("\n"))


def _apply_at_line_position(content: str, search: str, replace: str) -> str:
    """
    Find search block by matching stripped lines, then replace
    the corresponding lines in the original content.
    """
    content_lines = content.split("\n")
    search_lines = search.rstrip("\n").split("\n")
    search_stripped = [line.rstrip() for line in search_lines]
    n = len(search_lines)

    for i in range(len(content_lines) - n + 1):
        chunk = [line.rstrip() for line in content_lines[i:i + n]]
        if chunk == search_stripped:
            replace_lines = replace.rstrip("\n").split("\n")
            result_lines = content_lines[:i] + replace_lines + content_lines[i + n:]
            return "\n".join(result_lines)

    return ""


def _replace_with_flexible_whitespace(content: str, search: str, replace: str) -> str:
    """
    Handle LLM-generated edits that have different indentation.
    Adapted from aider's replace_part_with_missing_leading_whitespace.
    """
    content_lines = content.splitlines(keepends=True)
    search_lines = search.splitlines(keepends=True)
    replace_lines = replace.splitlines(keepends=True)

    if not search_lines:
        return ""

    # Calculate minimum leading whitespace in search + replace
    leading = []
    for line in search_lines + replace_lines:
        if line.strip():
            leading.append(len(line) - len(line.lstrip()))

    if leading and min(leading) > 0:
        num_leading = min(leading)
        search_lines = [l[num_leading:] if l.strip() else l for l in search_lines]
        replace_lines = [l[num_leading:] if l.strip() else l for l in replace_lines]

    n = len(search_lines)
    for i in range(len(content_lines) - n + 1):
        chunk = content_lines[i:i + n]
        # Check if non-whitespace content matches
        if all(
            chunk[j].lstrip() == search_lines[j].lstrip()
            for j in range(n)
        ):
            # Calculate the whitespace offset
            offsets = set()
            for j in range(n):
                if chunk[j].strip():
                    orig_ws = len(chunk[j]) - len(chunk[j].lstrip())
                    search_ws = len(search_lines[j]) - len(search_lines[j].lstrip())
                    offsets.add(chunk[j][:orig_ws - search_ws] if orig_ws >= search_ws else "")

            if len(offsets) == 1:
                add_ws = offsets.pop()
                adjusted = [add_ws + l if l.strip() else l for l in replace_lines]
                result = content_lines[:i] + adjusted + content_lines[i + n:]
                return "".join(result)

    return ""


def _replace_most_similar(content: str, search: str, replace: str, threshold: float = 0.75) -> str:
    """
    Fuzzy match: find the most similar chunk in content and replace it.
    Only used as last resort — requires high similarity threshold.
    """
    content_lines = content.splitlines(keepends=True)
    search_lines = search.splitlines(keepends=True)
    n = len(search_lines)

    if n == 0 or len(content_lines) < n:
        return ""

    best_ratio = 0.0
    best_start = -1

    # Search with some tolerance on chunk size
    for length in range(max(1, n - 2), min(len(content_lines), n + 3)):
        for i in range(len(content_lines) - length + 1):
            chunk = "".join(content_lines[i:i + length])
            ratio = SequenceMatcher(None, chunk, search).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_start = i
                best_length = length

    if best_ratio < threshold:
        return ""

    replace_lines = replace.splitlines(keepends=True)
    result = content_lines[:best_start] + replace_lines + content_lines[best_start + best_length:]
    return "".join(result)
