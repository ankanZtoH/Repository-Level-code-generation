"""
AI Code Agent — Phase 2: Tools
Structured tool definitions and execution for the agent.

ALLOWED TOOLS:
  - read_file
  - write_file
  - run_code
  - search_files

Supports ALL standard languages (Python, C, C++, Java, JS, HTML, CSS).
patch_function is permanently REMOVED.
"""

import os
from utils.logger import log
from utils.file_ops import read_file, write_file, search_files
from utils.executor import run_code, can_execute, NON_EXECUTABLE


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
    "search_files": {
        "description": "Search for a string in all files within a directory",
        "parameters": {"directory": "string (directory path)", "query": "string (search term)"},
    },
}


# ─── Tool Name Normalization ────────────────────────────────

TOOL_ALIASES = {
    "edit_file": "write_file",
    "edit": "write_file",
    "read": "read_file",
    "run": "run_code",
    "search": "search_files",
    "create_file": "write_file",
}

# Blocked tools — will return an error if LLM tries to use them
BLOCKED_TOOLS = {"patch_function", "list_directory"}


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
        return "Error: Tool not allowed. Use only: read_file, write_file, run_code, search_files"

    if tool_name not in TOOLS:
        return f"Error: Unknown tool '{tool_name}'. Use only: read_file, write_file, run_code, search_files"

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
