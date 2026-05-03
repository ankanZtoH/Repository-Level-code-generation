"""
AI Code Agent — Phase 2: Tools
Structured tool definitions and execution for the agent.

ALLOWED TOOLS:
  - read_file
  - write_file
  - run_code
  - run_tests
  - search_files

Supports ALL standard languages (Python, C, C++, Java, JS, HTML, CSS).
patch_function is permanently REMOVED.
"""

import os
from utils.logger import log
from utils.file_ops import read_file, write_file, search_files
from utils.validator import validate_syntax
from utils.safe_edit import patch_file as _patch_file_impl
from utils.executor import run_code, run_tests, can_execute, NON_EXECUTABLE


# ─── Supported file extensions ──────────────────────────────

SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".c", ".cpp", ".h", ".hpp",
    ".java",
    ".html", ".css", ".scss",
    ".rb", ".go", ".rs", ".sh",
    ".json", ".xml", ".yaml", ".yml",
    ".md", ".txt",
}


# ─── Tool Registry ──────────────────────────────────────────

TOOLS = {
    "read_file": {
        "description": "Read the contents of a file",
        "parameters": {"path": "string (file path)"},
    },
    "write_file": {
        "description": "Write content to a file (creates or overwrites). Content MUST be the ENTIRE file.",
        "parameters": {"path": "string (file path)", "content": "string (entire file content)"},
    },
    "run_code": {
        "description": "Execute a code file and return output/errors. Supports Python, C, C++, Java, JS. HTML/CSS files return success immediately.",
        "parameters": {"path": "string (file path)"},
    },
    "run_tests": {
        "description": "Detect and run the repository's test suite when one exists.",
        "parameters": {"directory": "string (repository directory path, optional)"},
    },
    "search_files": {
        "description": "Search for a string in all files within a directory",
        "parameters": {"directory": "string (directory path)", "query": "string (search term)"},
    },
    "patch_file": {
        "description": "Apply partial edits to a file using search/replace blocks. Safer than write_file for modifying existing files.",
        "parameters": {"path": "string (file path)", "edits": "list of {search, replace} dicts"},
    },
}


# ─── Tool Name Normalization ────────────────────────────────

TOOL_ALIASES = {
    "edit_file": "patch_file",
    "edit": "patch_file",
    "read": "read_file",
    "run": "run_code",
    "test": "run_tests",
    "tests": "run_tests",
    "run_test": "run_tests",
    "search": "search_files",
    "create_file": "write_file",
    "patch": "patch_file",
}

# Blocked tools — will return an error if LLM tries to use them
BLOCKED_TOOLS = {"list_directory"}


def normalize_tool_name(name: str) -> str:
    """Normalize a tool name, resolving aliases. Block disallowed tools."""
    name = name.strip().lower()
    if name in BLOCKED_TOOLS:
        return ""
    return TOOL_ALIASES.get(name, name)


def get_tools_description() -> str:
    """Return a formatted description of all available tools for LLM context."""
    lines = ["Available Tools:"]
    for name, info in TOOLS.items():
        params = ", ".join(f"{k}: {v}" for k, v in info["parameters"].items())
        lines.append(f"  {name}({params}) -- {info['description']}")
    return "\n".join(lines)


def get_tools_prompt() -> str:
    """
    Generate a detailed tool usage guide for SWE-agent system prompt.
    The LLM uses this to understand what tools are available and their JSON format.
    """
    return """## AVAILABLE TOOLS

You MUST respond with a JSON object containing "thought" and "action" fields.

### read_file
Read a file's contents.
{"thought": "I need to read this file to understand the code", "action": {"tool": "read_file", "path": "filename.py"}}

### write_file
Write/overwrite a file. Content must be the COMPLETE file.
{"thought": "I will write the fixed file", "action": {"tool": "write_file", "path": "filename.py", "content": "ENTIRE FILE CONTENT"}}

### patch_file
Apply targeted search/replace edits (safer than write_file for existing files).
{"thought": "I will fix the specific function", "action": {"tool": "patch_file", "path": "filename.py", "edits": [{"search": "old code", "replace": "new code"}]}}

### run_code
Execute a file and see output/errors.
{"thought": "Let me run the code to check for errors", "action": {"tool": "run_code", "path": "filename.py"}}

### run_tests
Run the test suite.
{"thought": "Let me verify with tests", "action": {"tool": "run_tests"}}

### search_files
Search for a string across all files.
{"thought": "I need to find where this function is defined", "action": {"tool": "search_files", "directory": ".", "query": "function_name"}}

### done
Signal that the task is complete.
{"thought": "The bug is fixed and tests pass", "action": {"tool": "done"}, "summary": "Fixed the issue by..."}

## RULES
- Always include "thought" explaining your reasoning
- Use read_file BEFORE editing to understand the code
- Use run_code or run_tests AFTER editing to verify
- NEVER guess file contents — always read first
- Signal "done" when the task is complete or you cannot make progress"""


# ─── File Type Guards ───────────────────────────────────────

def _is_supported_file(path: str) -> bool:
    """Check if a path refers to a supported file type."""
    ext = os.path.splitext(path)[1].lower()
    return ext in SUPPORTED_EXTENSIONS


def _get_language_name(path: str) -> str:
    """Get a human-readable language name from file path."""
    ext_names = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
        ".c": "C", ".cpp": "C++", ".h": "C Header", ".hpp": "C++ Header",
        ".java": "Java", ".html": "HTML", ".css": "CSS",
        ".rb": "Ruby", ".go": "Go", ".rs": "Rust", ".sh": "Shell",
    }
    ext = os.path.splitext(path)[1].lower()
    return ext_names.get(ext, ext)


# ─── Tool Execution ─────────────────────────────────────────

def execute_tool(action: dict, repo_path: str = ".") -> str:
    """
    Execute a tool action and return the observation string.
    Supports all standard languages.
    """
    tool_name = action.get("tool", action.get("action", ""))
    tool_name = normalize_tool_name(tool_name)

    if not tool_name:
        return "Error: Tool not allowed. Use only: read_file, write_file, run_code, run_tests, search_files"

    if tool_name not in TOOLS:
        return f"Error: Unknown tool '{tool_name}'. Use only: read_file, write_file, run_code, run_tests, search_files"

    try:
        if tool_name == "read_file":
            path = _resolve_path(action.get("path", action.get("file", "")), repo_path)
            content = read_file(path)
            if content:
                if len(content) > 3000:
                    return f"[File: {path}]\n{content[:3000]}\n... (truncated, {len(content)} chars total)"
                return f"[File: {path}]\n{content}"
            return f"Error: Could not read file '{path}'"

        elif tool_name == "write_file":
            path = _resolve_path(action.get("path", action.get("file", "")), repo_path)
            content = action.get("content", "")
            if not content:
                return "Error: No content provided for write_file"
            # Pre-write syntax validation
            valid, err = validate_syntax(content, path)
            if not valid:
                return f"Error: Syntax validation failed for {path}: {err}"
            success = write_file(path, content)
            return f"Successfully wrote to {path}" if success else f"Error writing to {path}"

        elif tool_name == "run_code":
            path = _resolve_path(action.get("path", action.get("file", "")), repo_path)
            result = run_code(path)
            output_parts = []
            if result["stdout"]:
                output_parts.append(f"STDOUT:\n{result['stdout']}")
            if result["stderr"]:
                output_parts.append(f"STDERR:\n{result['stderr']}")
            output_parts.append(f"Return code: {result['returncode']}")
            return "\n".join(output_parts)

        elif tool_name == "run_tests":
            directory = action.get("directory", action.get("path", ""))
            test_root = _resolve_path(directory, repo_path)
            result = run_tests(test_root)
            output_parts = []
            if result.get("command"):
                output_parts.append(f"Test command: {result['command']}")
            if result.get("skipped"):
                output_parts.append("Tests skipped: no test command detected")
            if result["stdout"]:
                output_parts.append(f"STDOUT:\n{result['stdout']}")
            if result["stderr"]:
                output_parts.append(f"STDERR:\n{result['stderr']}")
            output_parts.append(f"Return code: {result['returncode']}")
            return "\n".join(output_parts)

        elif tool_name == "search_files":
            directory = action.get("directory", repo_path)
            query = action.get("query", "")
            results = search_files(directory, query)
            if results:
                lines = [f"Found {len(results)} matches for '{query}':"]
                for fpath, lineno, line in results[:20]:
                    lines.append(f"  {fpath}:{lineno}: {line}")
                return "\n".join(lines)
            return f"No matches found for '{query}'"

        elif tool_name == "patch_file":
            path = _resolve_path(action.get("path", action.get("file", "")), repo_path)
            edits = action.get("edits", [])
            if not edits:
                return "Error: No edits provided for patch_file"
            success, msg = _patch_file_impl(path, edits)
            return msg if success else f"Error: {msg}"

        else:
            return f"Error: Unknown tool '{tool_name}'"

    except Exception as e:
        log("ERROR", f"Tool execution failed: {e}")
        return f"Error executing {tool_name}: {str(e)}"


def _resolve_path(path: str, repo_path: str) -> str:
    """Resolve a relative path against the repo root."""
    if not path:
        return repo_path
    if os.path.isabs(path):
        return path
    return os.path.join(repo_path, path)
