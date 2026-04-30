"""
AI Code Agent — Phase 2: Repo Analyzer
Analyzes repository structure for ALL supported languages.
Extracts functions/classes via AST for Python files.
Other languages get basic file info (size, extension).
"""

import os
import ast
import re
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
        else:
            source = read_file(filepath)
            info["imports"] = extract_non_python_imports(source, language)

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


# ─── Dependency Graph ───────────────────────────────────────

def extract_imports(source: str) -> list:
    """
    Extract imported module names from Python source using regex.
    Works even if the file has syntax errors (no AST needed).
    
    Returns list of module base names, e.g.:
        'from math_utils import multiply'  ->  ['math_utils']
        'import os, sys'                   ->  ['os', 'sys']
        'from .processor import func'      ->  ['processor']
    """
    modules = []
    for line in source.splitlines():
        line = line.strip()
        if line.startswith("#"):
            continue
        # from X import Y  /  from .X import Y
        m = re.match(r"from\s+\.?(\w[\w.]*)\s+import", line)
        if m:
            modules.append(m.group(1).split(".")[0])
            continue
        # import X, Y
        m = re.match(r"import\s+(.+)", line)
        if m:
            for part in m.group(1).split(","):
                name = part.strip().split()[0].split(".")[0]
                if name:
                    modules.append(name)
    return modules


def extract_non_python_imports(source: str, language: str) -> list:
    """
    Extract lightweight dependency references for non-Python source.
    Returns raw import/reference strings that can be resolved against repo files.
    """
    if not source:
        return []

    if language in ("javascript", "typescript"):
        return _extract_js_imports(source)

    if language in ("c", "cpp"):
        return re.findall(r'^\s*#\s*include\s+"([^"]+)"', source, re.MULTILINE)

    if language == "html":
        refs = re.findall(r'\b(?:src|href)\s*=\s*["\']([^"\']+)["\']', source, re.IGNORECASE)
        return [_clean_asset_ref(ref) for ref in refs if _is_local_asset_ref(ref)]

    if language == "css":
        refs = []
        refs.extend(re.findall(r'@import\s+(?:url\()?["\']?([^"\')]+)', source, re.IGNORECASE))
        refs.extend(re.findall(r'url\(["\']?([^"\')]+)', source, re.IGNORECASE))
        return [_clean_asset_ref(ref) for ref in refs if _is_local_asset_ref(ref)]

    return []


def extract_dependency_graph(repo_path: str, file_infos: list) -> dict:
    """
    Build a dependency graph: {relative_path: [relative_paths_it_imports]}.
    Only includes files that actually exist in the repo.

    Args:
        repo_path:  absolute path to the repo root
        file_infos: list of file info dicts from analyze_repo()

    Returns:
        {"main.py": ["processor.py", "formatter.py"], "processor.py": ["math_utils.py"]}
    """
    # Maps for fast resolution.
    basename_to_rel = {}
    rel_to_rel = {}
    for fi in file_infos:
        rel_norm = _norm_rel(fi["relative"])
        rel_to_rel[rel_norm] = fi["relative"]
        basename_to_rel[os.path.basename(rel_norm)] = fi["relative"]
        base = os.path.splitext(os.path.basename(rel_norm))[0]
        basename_to_rel.setdefault(base, fi["relative"])

    graph = {}
    for fi in file_infos:
        rel = fi["relative"]
        source = read_file(fi["path"])
        imported_modules = []
        if source:
            if fi.get("language") == "python":
                imported_modules = extract_imports(source)
            else:
                imported_modules = fi.get("imports") or extract_non_python_imports(
                    source,
                    fi.get("language", ""),
                )

        deps = []
        for ref in imported_modules:
            dep = _resolve_dependency_ref(ref, rel, rel_to_rel, basename_to_rel)
            if dep and dep != rel and dep not in deps:
                deps.append(dep)
        graph[rel] = deps
    return graph


def _extract_js_imports(source: str) -> list:
    """Extract import/require references from JavaScript or TypeScript."""
    refs = []
    patterns = [
        r'\bfrom\s+["\']([^"\']+)["\']',
        r'\bimport\s*\(\s*["\']([^"\']+)["\']\s*\)',
        r'\bimport\s+["\']([^"\']+)["\']',
        r'\brequire\s*\(\s*["\']([^"\']+)["\']\s*\)',
    ]
    for pattern in patterns:
        refs.extend(re.findall(pattern, source))
    return [ref for ref in refs if _is_local_module_ref(ref)]


def _resolve_dependency_ref(
    ref: str,
    current_rel: str,
    rel_to_rel: dict,
    basename_to_rel: dict,
) -> str:
    """Resolve a raw import/reference string to a repo-relative file path."""
    if not ref:
        return ""

    ref = _clean_asset_ref(ref)
    if not ref:
        return ""

    if ref in basename_to_rel:
        return basename_to_rel[ref]

    current_dir = os.path.dirname(_norm_rel(current_rel))
    candidates = []
    if ref.startswith((".", "/")) or "/" in ref:
        ref_path = ref.lstrip("/")
        if ref.startswith("."):
            ref_path = os.path.normpath(os.path.join(current_dir, ref))
        candidates.extend(_dependency_candidates(ref_path))
    else:
        candidates.extend(_dependency_candidates(ref))

    for candidate in candidates:
        candidate = _norm_rel(candidate)
        if candidate in rel_to_rel:
            return rel_to_rel[candidate]
        base = os.path.basename(candidate)
        if base in basename_to_rel:
            return basename_to_rel[base]
        stem = os.path.splitext(base)[0]
        if stem in basename_to_rel:
            return basename_to_rel[stem]

    return ""


def _dependency_candidates(path: str) -> list:
    """Return likely file candidates for an import/reference path."""
    norm = _norm_rel(path)
    _, ext = os.path.splitext(norm)
    candidates = [norm]

    if not ext:
        for suffix in SUPPORTED_EXTENSIONS:
            candidates.append(norm + suffix)
        for suffix in SUPPORTED_EXTENSIONS:
            candidates.append(os.path.join(norm, "index" + suffix))

    return candidates


def _is_local_module_ref(ref: str) -> bool:
    """Return True for relative/local JS module references."""
    return ref.startswith(".") or ref.startswith("/")


def _is_local_asset_ref(ref: str) -> bool:
    """Return True for local HTML/CSS asset references."""
    ref = ref.strip()
    lowered = ref.lower()
    if not ref or ref.startswith("#"):
        return False
    return not (
        lowered.startswith("http://")
        or lowered.startswith("https://")
        or lowered.startswith("data:")
        or lowered.startswith("mailto:")
        or lowered.startswith("tel:")
    )


def _clean_asset_ref(ref: str) -> str:
    """Strip URL fragments/query strings from a dependency reference."""
    return ref.strip().rstrip(";").split("#", 1)[0].split("?", 1)[0]


def _norm_rel(path: str) -> str:
    """Normalize a relative path while preserving repo-relative semantics."""
    return os.path.normpath(path).replace("\\", "/")
