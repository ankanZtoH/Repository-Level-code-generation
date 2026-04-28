"""
AI Code Agent — Phase 2: Repo Analyzer
Analyzes repository structure for ALL supported languages.
Extracts functions/classes via AST for Python files.
Other languages get basic file info (size, extension).
"""

import os
import ast
from utils.logger import log, separator
from utils.file_ops import list_files, read_file


# Supported code file extensions
SUPPORTED_EXTENSIONS = [
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".c", ".cpp", ".h", ".hpp",
    ".java",
    ".html", ".css", ".scss",
    ".rb", ".go", ".rs", ".sh",
]


# ─── Public API ─────────────────────────────────────────────

def analyze_repo(repo_path: str) -> dict:
    """
    Analyze a repository and return a structured map.
    Includes ALL supported code file types.

    Returns:
        {
            "path": str,
            "files": [FileInfo],
            "summary": str,
        }
    """
    separator("Repo Analysis")
    abs_path = os.path.abspath(repo_path)
    log("INFO", f"Analyzing repository: {abs_path}")

    all_files = list_files(abs_path, extensions=SUPPORTED_EXTENSIONS)
    file_infos = []

    for fpath in all_files:
        info = _analyze_file(fpath, abs_path)
        if info:
            file_infos.append(info)

    # Build summary
    lang_counts = {}
    total_funcs = 0
    for f in file_infos:
        lang = f["language"]
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
        total_funcs += len(f.get("functions", []))

    summary_parts = [f"{count} {lang}" for lang, count in sorted(lang_counts.items())]
    summary = f"{len(file_infos)} files ({', '.join(summary_parts)}), {total_funcs} functions"

    log("RESULT", summary)

    return {
        "path": abs_path,
        "files": file_infos,
        "summary": summary,
    }


def get_repo_map_text(analysis: dict) -> str:
    """Generate a compact repo map string for LLM context."""
    lines = [f"Repository: {analysis['path']}", f"Summary: {analysis['summary']}", ""]

    for f in analysis["files"]:
        lines.append(f"{f['relative']}  ({f['language']}, {f['size']}B)")

        if f.get("has_syntax_error"):
            lines.append("   !!! SYNTAX ERROR DETECTED !!!")

        if f.get("functions"):
            for func in f["functions"]:
                args_str = ", ".join(func["args"][:4])
                lines.append(f"   def {func['name']}({args_str})  L{func['lineno']}")

        if f.get("classes"):
            for cls in f["classes"]:
                methods_str = ", ".join(cls["methods"][:5])
                lines.append(f"   class {cls['name']} [{methods_str}]")

        lines.append("")

    return "\n".join(lines)


# ─── File Analysis ───────────────────────────────────────────

LANGUAGE_MAP = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "javascript", ".tsx": "typescript",
    ".java": "java", ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
    ".html": "html", ".css": "css", ".scss": "css",
    ".rb": "ruby", ".go": "go", ".rs": "rust", ".sh": "bash",
}


def _analyze_file(filepath: str, repo_root: str) -> dict:
    """Analyze a single file. Returns None on error."""
    try:
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in LANGUAGE_MAP:
            return None

        relative = os.path.relpath(filepath, repo_root)
        language = LANGUAGE_MAP[ext]
        size = os.path.getsize(filepath)

        info = {
            "path": filepath,
            "relative": relative,
            "language": language,
            "size": size,
            "functions": [],
            "classes": [],
            "imports": [],
            "has_syntax_error": False,
        }

        # Deep AST analysis only for Python
        if language == "python":
            info["has_syntax_error"] = not _analyze_python(filepath, info)

        return info
    except Exception:
        return None


def _analyze_python(filepath: str, info: dict) -> bool:
    """Extract functions, classes, and imports. Returns False on syntax error."""
    source = read_file(filepath)
    if not source:
        return True

    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        log("INFO", f"Skipping AST parse for {filepath} (syntax error)")
        return False
    except Exception as e:
        log("INFO", f"AST analysis failed for {filepath}: {e}")
        return True

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info["functions"].append({
                "name": node.name,
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", node.lineno),
                "args": [arg.arg for arg in node.args.args],
            })

        elif isinstance(node, ast.ClassDef):
            methods = [
                n.name for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            info["classes"].append({
                "name": node.name,
                "lineno": node.lineno,
                "methods": methods,
            })

        elif isinstance(node, ast.Import):
            for alias in node.names:
                info["imports"].append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                info["imports"].append(f"{module}.{alias.name}")
    
    return True