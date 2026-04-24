"""
AI Code Agent — File Operations
Safe file read/write/search utilities.
"""

import os
from utils.logger import log


def read_file(path: str) -> str:
    """Read and return file contents. Returns empty string on failure."""
    try:
        abs_path = os.path.abspath(path)
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        log("TOOL", f"Read {len(content)} chars from {abs_path}")
        return content
    except FileNotFoundError:
        log("ERROR", f"File not found: {path}")
        return ""
    except Exception as e:
        log("ERROR", f"Failed to read {path}: {e}")
        return ""


def write_file(path: str, content: str) -> bool:
    """Write content to a file. Creates parent directories if needed."""
    try:
        abs_path = os.path.abspath(path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        log("TOOL", f"Wrote {len(content)} chars to {abs_path}")
        return True
    except Exception as e:
        log("ERROR", f"Failed to write {path}: {e}")
        return False


def search_files(directory: str, query: str) -> list:
    """
    Search for files containing the query string.
    Returns list of (filepath, line_number, line_content) tuples.
    """
    results = []
    query_lower = query.lower()
    abs_dir = os.path.abspath(directory)

    if not os.path.isdir(abs_dir):
        log("ERROR", f"Directory not found: {directory}")
        return results

    for root, dirs, files in os.walk(abs_dir):
        # Skip hidden dirs and __pycache__
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if query_lower in line.lower():
                            results.append((fpath, i, line.strip()))
            except Exception:
                continue

    log("TOOL", f"Search '{query}' in {abs_dir}: {len(results)} matches")
    return results


def list_files(directory: str, extensions: list = None) -> list:
    """List all files in a directory, optionally filtered by extension."""
    result = []
    abs_dir = os.path.abspath(directory)

    if not os.path.isdir(abs_dir):
        log("ERROR", f"Directory not found: {directory}")
        return result

    for root, dirs, files in os.walk(abs_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for fname in files:
            if extensions:
                if not any(fname.endswith(ext) for ext in extensions):
                    continue
            result.append(os.path.join(root, fname))

    return result
