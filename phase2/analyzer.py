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

    dependency_graph = extract_dependency_graph(abs_path, file_infos)
    reverse_dependency_graph = build_reverse_dependency_graph(dependency_graph)
    call_graph = extract_function_call_graph(file_infos)
    code_tree = build_hierarchical_code_tree(file_infos)
    important_files = rank_important_files(file_infos, dependency_graph, reverse_dependency_graph)
    importance_by_path = {item["relative"]: item["score"] for item in important_files}
    for f in file_infos:
        f["importance"] = importance_by_path.get(f["relative"], 0)

    summary_parts = [f"{count} {lang}" for lang, count in sorted(lang_counts.items())]
    summary = f"{len(file_infos)} files ({', '.join(summary_parts)}), {total_funcs} functions"

    log("RESULT", summary)

    return {
        "path": abs_path,
        "files": file_infos,
        "summary": summary,
        "dependency_graph": dependency_graph,
        "reverse_dependency_graph": reverse_dependency_graph,
        "call_graph": call_graph,
        "code_tree": code_tree,
        "important_files": important_files,
    }


def get_repo_map_text(analysis: dict) -> str:
    """Generate a compact repo map string for LLM context."""
    lines = [f"Repository: {analysis['path']}", f"Summary: {analysis['summary']}", ""]

    important = analysis.get("important_files", [])[:8]
    if important:
        lines.append("Important files:")
        for item in important:
            reasons = ", ".join(item.get("reasons", [])[:3])
            reason_text = f" — {reasons}" if reasons else ""
            lines.append(f"   {item['relative']}  score={item['score']}{reason_text}")
        lines.append("")

    dep_graph = analysis.get("dependency_graph", {})
    if dep_graph:
        lines.append("Module dependency graph:")
        for src, deps in list(dep_graph.items())[:20]:
            if deps:
                lines.append(f"   {src} -> {', '.join(deps[:5])}")
        lines.append("")

    call_graph = analysis.get("call_graph", [])
    if call_graph:
        lines.append("Function call graph:")
        for edge in call_graph[:20]:
            lines.append(f"   {edge['caller']} -> {edge['callee']}")
        lines.append("")

    for f in analysis["files"]:
        lines.append(f"{f['relative']}  ({f['language']}, {f['size']}B)")

        if f.get("has_syntax_error"):
            lines.append("   !!! SYNTAX ERROR DETECTED !!!")

        if f.get("functions"):
            for func in f["functions"]:
                args_str = ", ".join(func["args"][:4])
                calls = func.get("calls", [])
                call_text = f" calls: {', '.join(calls[:5])}" if calls else ""
                lines.append(f"   def {func['name']}({args_str})  L{func['lineno']}{call_text}")

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
                "calls": _extract_python_calls(node),
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


def _extract_python_calls(node: ast.AST) -> list:
    """Extract function or method call names from a Python AST node."""
    calls = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue

        name = ""
        if isinstance(child.func, ast.Name):
            name = child.func.id
        elif isinstance(child.func, ast.Attribute):
            name = _attribute_to_name(child.func)

        if name and name not in calls:
            calls.append(name)
    return calls


def _attribute_to_name(node: ast.Attribute) -> str:
    """Convert an attribute expression to a dotted name when possible."""
    parts = [node.attr]
    value = node.value
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    parts.reverse()
    return ".".join(parts)


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


def build_reverse_dependency_graph(dependency_graph: dict) -> dict:
    """Build {file: [files_that_depend_on_it]} from a dependency graph."""
    reverse = {src: [] for src in dependency_graph}
    for src, deps in dependency_graph.items():
        for dep in deps:
            reverse.setdefault(dep, [])
            if src not in reverse[dep]:
                reverse[dep].append(src)
    return reverse


def extract_function_call_graph(file_infos: list) -> list:
    """
    Build lightweight function call edges using Python AST call names.
    Edges are best-effort and intentionally conservative.
    """
    function_index = {}
    for fi in file_infos:
        if fi.get("language") != "python":
            continue
        for func in fi.get("functions", []):
            node_id = f"{fi['relative']}:{func['name']}"
            function_index.setdefault(func["name"], []).append(node_id)

    edges = []
    seen = set()
    for fi in file_infos:
        if fi.get("language") != "python":
            continue
        for func in fi.get("functions", []):
            caller = f"{fi['relative']}:{func['name']}"
            for call in func.get("calls", []):
                short = call.split(".")[-1]
                for callee in function_index.get(short, []):
                    if callee == caller:
                        continue
                    key = (caller, callee)
                    if key in seen:
                        continue
                    seen.add(key)
                    edges.append({"caller": caller, "callee": callee})
    return edges


def build_hierarchical_code_tree(file_infos: list) -> dict:
    """
    Build a lightweight package -> file -> symbols tree inspired by RepoMaster's HCT.
    """
    root = {"name": "", "type": "directory", "children": {}, "files": []}
    for fi in sorted(file_infos, key=lambda item: item["relative"]):
        parts = _norm_rel(fi["relative"]).split("/")
        node = root
        for part in parts[:-1]:
            node = node["children"].setdefault(
                part,
                {"name": part, "type": "directory", "children": {}, "files": []},
            )
        node["files"].append({
            "name": parts[-1],
            "relative": fi["relative"],
            "language": fi["language"],
            "functions": [func["name"] for func in fi.get("functions", [])],
            "classes": [cls["name"] for cls in fi.get("classes", [])],
        })
    return root


def rank_important_files(file_infos: list, dependency_graph: dict, reverse_dependency_graph: dict) -> list:
    """
    Rank files by structural importance.
    Uses RepoMaster-style signals: dependency centrality, entry-like names,
    code symbols, syntax errors, and semantic filename hints.
    """
    entry_names = {"main.py", "app.py", "run.py", "start.py", "__main__.py", "server.py"}
    semantic_keywords = {
        "core", "main", "app", "server", "agent", "router", "service",
        "manager", "processor", "pipeline", "executor", "config", "model",
    }
    ranked = []
    for fi in file_infos:
        rel = fi["relative"]
        base = os.path.basename(rel).lower()
        stem = os.path.splitext(base)[0]
        reasons = []
        score = 0

        incoming = len(reverse_dependency_graph.get(rel, []))
        outgoing = len(dependency_graph.get(rel, []))
        if incoming:
            score += incoming * 4
            reasons.append(f"imported_by={incoming}")
        if outgoing:
            score += outgoing * 2
            reasons.append(f"depends_on={outgoing}")

        if base in entry_names:
            score += 8
            reasons.append("entry_candidate")
        if stem in semantic_keywords or any(word in stem for word in semantic_keywords):
            score += 3
            reasons.append("semantic_name")

        symbol_count = len(fi.get("functions", [])) + len(fi.get("classes", []))
        if symbol_count:
            score += min(symbol_count, 6)
            reasons.append(f"symbols={symbol_count}")

        if fi.get("has_syntax_error"):
            score += 10
            reasons.append("syntax_error")

        if _looks_like_test_file(rel):
            score -= 5
            reasons.append("test_file")

        ranked.append({
            "relative": rel,
            "score": round(score, 2),
            "reasons": reasons,
        })

    ranked.sort(key=lambda item: (-item["score"], item["relative"]))
    return ranked


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


def _looks_like_test_file(rel_path: str) -> bool:
    """Return True for common test-file naming conventions."""
    norm = _norm_rel(rel_path).lower()
    base = os.path.basename(norm)
    return (
        norm.startswith("tests/")
        or "/tests/" in norm
        or base.startswith("test_")
        or base.endswith("_test.py")
        or base.endswith(".test.js")
        or base.endswith(".spec.js")
        or base.endswith(".test.ts")
        or base.endswith(".spec.ts")
    )


def _clean_asset_ref(ref: str) -> str:
    """Strip URL fragments/query strings from a dependency reference."""
    return ref.strip().rstrip(";").split("#", 1)[0].split("?", 1)[0]


def _norm_rel(path: str) -> str:
    """Normalize a relative path while preserving repo-relative semantics."""
    return os.path.normpath(path).replace("\\", "/")


# ─── Semantic Dependency Graph (FIX POINT 1) ────────────────

MAX_LINES_FOR_AST = 10000  # FIX POINT 5: skip huge files


def build_semantic_graph(file_infos: list, import_graph: dict = None) -> dict:
    """
    Build a semantic dependency graph that combines:
      1. Import-level dependencies (from extract_dependency_graph)
      2. Function-call-level cross-file dependencies (from AST)

    Returns same format as extract_dependency_graph:
        {"main.py": ["service.py", "utils.py"], ...}

    Falls back to import_graph if AST analysis fails.
    """
    # Start with import graph as base
    graph = {}
    if import_graph:
        for src, deps in import_graph.items():
            graph[src] = list(deps)

    # Build function_name → file mapping
    function_to_file = {}
    for fi in file_infos:
        rel = fi.get("relative", "")
        # FIX POINT 5: skip large files
        if fi.get("size", 0) > MAX_LINES_FOR_AST * 80:  # ~80 chars/line
            continue
        for func in fi.get("functions", []):
            fname = func.get("name", "")
            if fname and fname not in ("__init__", "__str__", "__repr__"):
                function_to_file.setdefault(fname, rel)
        for cls in fi.get("classes", []):
            cname = cls.get("name", "")
            if cname:
                function_to_file.setdefault(cname, rel)

    # Map calls → files to find cross-file semantic edges
    for fi in file_infos:
        rel = fi.get("relative", "")
        if fi.get("size", 0) > MAX_LINES_FOR_AST * 80:
            continue
        graph.setdefault(rel, [])

        for func in fi.get("functions", []):
            for call_name in func.get("calls", []):
                # Strip module prefix: obj.method → method
                short = call_name.split(".")[-1]
                target_file = function_to_file.get(short, "")
                if target_file and target_file != rel and target_file not in graph[rel]:
                    graph[rel].append(target_file)

    return graph


def get_reverse_deps(dep_graph: dict, target: str) -> list:
    """
    FIX POINT 4: Get files that depend on the target file (reverse deps).
    Useful for understanding impact of changes.
    """
    reverse = []
    for src, deps in dep_graph.items():
        if target in deps and src not in reverse:
            reverse.append(src)
    return reverse


# ─── Terminal Graph Visualization (FIX POINT 3) ─────────────

def print_dependency_graph(dep_graph: dict, title: str = "Dependency Graph") -> str:
    """
    Generate a tree-like terminal visualization of the dependency graph.
    
    Returns the visualization as a string (also logs it).
    
    Example output:
        Dependency Graph:
        main.py
        ├── service.py
        │   └── utils.py
        └── config.py
    """
    if not dep_graph:
        return f"{title}: (empty)"

    # Find root nodes (files not imported by anyone, or all files if no clear root)
    all_files = set(dep_graph.keys())
    imported = set()
    for deps in dep_graph.values():
        imported.update(deps)
    roots = all_files - imported
    if not roots:
        roots = all_files  # No clear hierarchy, show all

    lines = [f"{title}:"]
    visited = set()

    def _render_tree(node: str, prefix: str = "", is_last: bool = True):
        """Recursively render a tree node."""
        if node in visited:
            lines.append(f"{prefix}{'└── ' if is_last else '├── '}{node} (circular)")
            return
        visited.add(node)

        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{node}")

        children = dep_graph.get(node, [])
        child_prefix = prefix + ("    " if is_last else "│   ")
        for i, child in enumerate(children):
            _render_tree(child, child_prefix, i == len(children) - 1)

    # Render each root
    sorted_roots = sorted(roots)
    for i, root in enumerate(sorted_roots):
        if i > 0:
            lines.append("")  # spacing between trees
        is_last_root = (i == len(sorted_roots) - 1)
        # Root nodes get no prefix
        if root in visited:
            continue
        visited.add(root)
        lines.append(f"  {root}")
        children = dep_graph.get(root, [])
        for j, child in enumerate(children):
            _render_tree(child, "  ", j == len(children) - 1)

    output = "\n".join(lines)
    log("INFO", output)
    return output


def format_graph_compact(dep_graph: dict) -> str:
    """
    Format dependency graph as compact arrow notation.
    Useful for LLM context where tree format is too verbose.
    
    Example: main.py → service.py, utils.py
    """
    lines = []
    for src, deps in sorted(dep_graph.items()):
        if deps:
            lines.append(f"  {src} → {', '.join(deps)}")
    return "\n".join(lines) if lines else "  (no dependencies)"
