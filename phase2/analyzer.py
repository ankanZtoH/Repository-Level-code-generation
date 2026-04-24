"""
AI Code Agent — Phase 2: Repo Analyzer
Analyzes repository structure, extracts functions via AST, and builds a codebase map.
Inspired by Aider's repo-map approach.
"""

import os
import ast
from utils.logger import log, separator
from utils.file_ops import list_files, read_file


def analyze_repo(repo_path: str) -> dict:
    """
    Analyze a repository and return a structured map.

    Returns:
        {
            "path": str,
            "files": [
                {
                    "path": str,
                    "relative": str,
                    "language": str,
                    "size": int,
                    "functions": [{"name": str, "lineno": int, "end_lineno": int, "args": [str]}],
                    "classes": [{"name": str, "lineno": int, "methods": [str]}],
                    "imports": [str],
                }
            ],
            "summary": str,
        }
    """
    separator("Repo Analysis")
    abs_path = os.path.abspath(repo_path)
    log("INFO", f"Analyzing repository: {abs_path}")

    all_files = list_files(abs_path)
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


def _analyze_file(filepath: str, repo_root: str) -> dict:
    """Analyze a single file."""
    try:
        relative = os.path.relpath(filepath, repo_root)
        language = _detect_language(filepath)
        size = os.path.getsize(filepath)

        info = {
            "path": filepath,
            "relative": relative,
            "language": language,
            "size": size,
            "functions": [],
            "classes": [],
            "imports": [],
        }

        # Deep analysis only for Python files (AST)
        if language == "python":
            _analyze_python(filepath, info)

        return info
    except Exception:
        return None


def _analyze_python(filepath: str, info: dict):
    """Extract functions, classes, and imports from Python files using AST."""
    try:
        source = read_file(filepath)
        if not source:
            return

        tree = ast.parse(source, filename=filepath)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                func_info = {
                    "name": node.name,
                    "lineno": node.lineno,
                    "end_lineno": getattr(node, "end_lineno", node.lineno),
                    "args": [arg.arg for arg in node.args.args],
                }
                info["functions"].append(func_info)

            elif isinstance(node, ast.ClassDef):
                methods = [
                    n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                class_info = {
                    "name": node.name,
                    "lineno": node.lineno,
                    "methods": methods,
                }
                info["classes"].append(class_info)

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    info["imports"].append(alias.name)

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    info["imports"].append(f"{module}.{alias.name}")

    except SyntaxError:
        log("INFO", f"Skipping AST parse for {filepath} (syntax error)")
    except Exception as e:
        log("INFO", f"AST analysis failed for {filepath}: {e}")


def get_repo_map_text(analysis: dict) -> str:
    """Generate a human-readable repo map string for LLM context."""
    lines = [f"Repository: {analysis['path']}", f"Summary: {analysis['summary']}", ""]

    for f in analysis["files"]:
        lines.append(f"📄 {f['relative']}  ({f['language']}, {f['size']}B)")

        if f["classes"]:
            for cls in f["classes"]:
                methods_str = ", ".join(cls["methods"][:5])
                lines.append(f"   class {cls['name']} [{methods_str}]")

        if f["functions"]:
            for func in f["functions"]:
                args_str = ", ".join(func["args"][:4])
                lines.append(f"   def {func['name']}({args_str})  L{func['lineno']}")

        if f["imports"]:
            imports_str = ", ".join(f["imports"][:5])
            if len(f["imports"]) > 5:
                imports_str += f" (+{len(f['imports'])-5} more)"
            lines.append(f"   imports: {imports_str}")

        lines.append("")

    return "\n".join(lines)


def _detect_language(filepath: str) -> str:
    """Detect language from file extension."""
    ext_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".java": "java", ".c": "c", ".cpp": "cpp", ".h": "c",
        ".html": "html", ".css": "css", ".rb": "ruby",
        ".go": "go", ".rs": "rust", ".sh": "bash",
        ".json": "json", ".xml": "xml", ".yaml": "yaml", ".yml": "yaml",
        ".md": "markdown", ".txt": "text",
    }
    ext = os.path.splitext(filepath)[1].lower()
    return ext_map.get(ext, "unknown")
