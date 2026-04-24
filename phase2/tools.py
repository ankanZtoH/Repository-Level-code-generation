"""
AI Code Agent — Phase 2: Tools (OpenHands-style)
Structured tool definitions and execution for the agent.
Each tool has a name, description, parameter schema, and executor.
"""

import os
import json
from utils.logger import log
from utils.file_ops import read_file, write_file, search_files
from utils.executor import run_code


# ─── Tool Registry ──────────────────────────────────────────

TOOLS = {
    "read_file": {
        "description": "Read the contents of a file",
        "parameters": {"path": "string (file path)"},
    },
    "write_file": {
        "description": "Write content to a file (creates or overwrites)",
        "parameters": {"path": "string (file path)", "content": "string (file content)"},
    },
    "search_files": {
        "description": "Search for a string in all files within a directory",
        "parameters": {"directory": "string (directory path)", "query": "string (search term)"},
    },
    "run_code": {
        "description": "Execute a code file and return output/errors",
        "parameters": {"path": "string (file path)"},
    },
    "list_directory": {
        "description": "List files in a directory",
        "parameters": {"path": "string (directory path)"},
    },
    "create_file": {
        "description": "Create a new file with content (errors if exists)",
        "parameters": {"path": "string (file path)", "content": "string (file content)"},
    },
    "edit_file": {
        "description": "Edit/overwrite a file with new content (alias for write_file)",
        "parameters": {"path": "string (file path)", "content": "string (file content)"},
    },
}


def get_tools_description() -> str:
    """Return a formatted description of all available tools for LLM context."""
    lines = ["Available Tools:"]
    for name, info in TOOLS.items():
        params = ", ".join(f"{k}: {v}" for k, v in info["parameters"].items())
        lines.append(f"  • {name}({params}) — {info['description']}")
    return "\n".join(lines)


TOOL_ALIASES = {
    "edit_file": "write_file", "edit": "write_file",
    "read": "read_file", "run": "run_code",
    "search": "search_files", "list": "list_directory",
}


def normalize_tool_name(name: str) -> str:
    """Normalize a tool name, resolving aliases."""
    return TOOL_ALIASES.get(name, name)


def execute_tool(action: dict, repo_path: str = ".") -> str:
    """
    Execute a tool action and return the observation string.

    action dict must have:
        - "tool": tool name
        - other keys matching tool parameters
    """
    tool_name = action.get("tool", action.get("action", ""))
    tool_name = normalize_tool_name(tool_name)

    log("TOOL", f"Executing: {tool_name}")

    try:
        if tool_name == "read_file":
            path = _resolve_path(action.get("path", action.get("file", "")), repo_path)
            content = read_file(path)
            if content:
                # Truncate very long files
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

        elif tool_name == "create_file":
            path = _resolve_path(action.get("path", action.get("file", "")), repo_path)
            content = action.get("content", "")
            if os.path.exists(path):
                return f"Error: File already exists: {path}. Use write_file to overwrite."
            success = write_file(path, content)
            return f"Created file: {path}" if success else f"Error creating {path}"

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

        elif tool_name == "list_directory":
            path = _resolve_path(action.get("path", ""), repo_path)
            if not os.path.isdir(path):
                return f"Error: Not a directory: {path}"
            entries = sorted(os.listdir(path))
            dirs = [e + "/" for e in entries if os.path.isdir(os.path.join(path, e))]
            files = [e for e in entries if os.path.isfile(os.path.join(path, e))]
            return f"Directory: {path}\nDirs: {dirs}\nFiles: {files}"

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
