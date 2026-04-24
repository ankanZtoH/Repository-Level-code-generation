"""
AI Code Agent — Phase 1: Local Code Editor
Direct code editing: Instruction + Code → LLM → Updated Code.
No agent loop, no tools — pure edit pipeline.
"""

import os
import difflib
from utils.logger import log, separator, banner
from utils.llm import query_llm, query_llm_json
from utils.file_ops import read_file, write_file
from phase1.prompts import (
    SYSTEM_PROMPT_EDITOR,
    SYSTEM_PROMPT_MULTI_FILE,
    build_edit_prompt,
    build_multi_file_prompt,
)


def show_diff(original: str, updated: str, filename: str = "file"):
    """Display a colored diff between original and updated code."""
    orig_lines = original.splitlines(keepends=True)
    new_lines = updated.splitlines(keepends=True)

    diff = difflib.unified_diff(
        orig_lines, new_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm=""
    )

    diff_text = ""
    for line in diff:
        line = line.rstrip("\n")
        if line.startswith("+") and not line.startswith("+++"):
            diff_text += f"\033[92m{line}\033[0m\n"  # Green
        elif line.startswith("-") and not line.startswith("---"):
            diff_text += f"\033[91m{line}\033[0m\n"  # Red
        elif line.startswith("@@"):
            diff_text += f"\033[96m{line}\033[0m\n"  # Cyan
        else:
            diff_text += line + "\n"

    if diff_text.strip():
        log("DIFF", f"Changes for {filename}:")
        print(diff_text)
    else:
        log("INFO", f"No changes detected in {filename}")


def edit_code(instruction: str, code: str, language: str = "python") -> str:
    """
    Phase 1 core: send instruction + code to LLM, get updated code.
    Returns the updated code string.
    """
    banner("PHASE 1 — CODE EDITOR")
    log("INFO", f"Instruction: {instruction}")
    log("INFO", f"Language: {language}")
    log("INFO", f"Code length: {len(code)} chars")

    separator("Sending to LLM")
    prompt = build_edit_prompt(instruction, code, language)
    updated = query_llm(prompt, system_prompt=SYSTEM_PROMPT_EDITOR)

    if not updated:
        log("ERROR", "LLM returned empty response")
        return code

    # Clean markdown fences if LLM wraps the code
    updated = _clean_code_fences(updated, language)

    separator("Diff")
    show_diff(code, updated, f"code.{_ext(language)}")

    log("RESULT", "Phase 1 edit complete")
    return updated


def edit_file(instruction: str, filepath: str) -> bool:
    """
    Phase 1: Edit a single file in-place.
    """
    code = read_file(filepath)
    if not code:
        log("ERROR", f"Cannot read {filepath}")
        return False

    language = _detect_language(filepath)
    updated = edit_code(instruction, code, language)

    if updated and updated != code:
        write_file(filepath, updated)
        log("RESULT", f"File updated: {filepath}")
        return True
    else:
        log("INFO", "No changes made")
        return False


def edit_multiple_files(instruction: str, filepaths: list) -> dict:
    """
    Phase 1: Edit multiple files using multi-file context.
    Returns dict of {filepath: updated_content}.
    """
    banner("PHASE 1 — MULTI-FILE EDITOR")
    log("INFO", f"Instruction: {instruction}")
    log("INFO", f"Files: {len(filepaths)}")

    files = {}
    for fp in filepaths:
        content = read_file(fp)
        if content:
            files[os.path.basename(fp)] = content

    if not files:
        log("ERROR", "No files could be read")
        return {}

    prompt = build_multi_file_prompt(instruction, files)
    result = query_llm_json(prompt, system_prompt=SYSTEM_PROMPT_MULTI_FILE)

    if not result:
        log("ERROR", "LLM returned empty response")
        return {}

    # Show diffs and write files
    updated_map = {}
    for fp in filepaths:
        fname = os.path.basename(fp)
        if fname in result:
            original = files.get(fname, "")
            updated = result[fname]
            separator(f"Diff — {fname}")
            show_diff(original, updated, fname)
            write_file(fp, updated)
            updated_map[fp] = updated

    log("RESULT", f"Updated {len(updated_map)} files")
    return updated_map


# ─── Helpers ────────────────────────────────────────────────

def _detect_language(filepath: str) -> str:
    """Detect language from file extension."""
    ext_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".java": "java", ".c": "c", ".cpp": "cpp", ".h": "c",
        ".html": "html", ".css": "css", ".rb": "ruby",
        ".go": "go", ".rs": "rust", ".sh": "bash",
    }
    ext = os.path.splitext(filepath)[1].lower()
    return ext_map.get(ext, "text")


def _ext(language: str) -> str:
    """Get file extension from language name."""
    lang_ext = {
        "python": "py", "javascript": "js", "typescript": "ts",
        "java": "java", "c": "c", "cpp": "cpp",
        "html": "html", "css": "css", "ruby": "rb",
    }
    return lang_ext.get(language, "txt")


def _clean_code_fences(text: str, language: str = "") -> str:
    """Remove markdown code fences from LLM output."""
    lines = text.strip().split("\n")

    # Check if first line is a code fence
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]

    # Check if last line is a code fence
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]

    return "\n".join(lines)
