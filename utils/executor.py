"""
AI Code Agent — Code Executor
Runs code files in subprocess with output/error capture.
Supports: Python, C, C++, Java, JavaScript, Ruby, Shell.
Non-runnable files (HTML, CSS) are not handled here.
"""

import subprocess
import os
import json
import sys
from utils.logger import log


# ─── Language → Command Mapping ─────────────────────────────
RUNNERS = {
    ".py":   ["python3"],
    ".js":   ["node"],
    ".rb":   ["ruby"],
    ".sh":   ["bash"],
}

# Languages that need compile-then-run
COMPILED_LANGUAGES = {".c", ".cpp", ".java"}

# Languages that can't be executed (just written)
NON_EXECUTABLE = {".html", ".css", ".scss", ".less", ".md", ".txt", ".json", ".xml", ".yaml", ".yml"}


def can_execute(filepath: str) -> bool:
    """Check if a file type can be executed."""
    ext = os.path.splitext(filepath)[1].lower()
    return ext in RUNNERS or ext in COMPILED_LANGUAGES


def run_code(filepath: str, timeout: int = 30) -> dict:
    """
    Execute a code file and return stdout, stderr, and return code.
    Supports Python, JS, C, C++, Java, Ruby, Shell.
    Returns error for non-executable files (HTML, CSS).
    """
    abs_path = os.path.abspath(filepath)
    if not os.path.isfile(abs_path):
        return {"stdout": "", "stderr": f"File not found: {filepath}", "returncode": 1}

    ext = os.path.splitext(abs_path)[1].lower()
    cwd = os.path.dirname(abs_path)
    basename = os.path.basename(abs_path)
    name_no_ext = os.path.splitext(basename)[0]

    if ext in NON_EXECUTABLE:
        return {
            "stdout": f"{basename} is a {ext} file — no execution needed. File written successfully.",
            "stderr": "",
            "returncode": 0,
        }

    log("TOOL", f"Running {basename} ...")

    try:
        if ext in (".c", ".cpp"):
            return _compile_and_run_c(abs_path, cwd, ext, timeout)
        elif ext == ".java":
            return _compile_and_run_java(abs_path, cwd, name_no_ext, timeout)
        elif ext in RUNNERS:
            cmd = RUNNERS[ext] + [abs_path]
            return _execute(cmd, cwd, timeout)
        else:
            return {"stdout": "", "stderr": f"Unsupported file type: {ext}", "returncode": 1}
    except subprocess.TimeoutExpired:
        log("ERROR", f"Execution timed out after {timeout}s")
        return {"stdout": "", "stderr": f"Timeout after {timeout}s", "returncode": -1}
    except Exception as e:
        log("ERROR", f"Execution failed: {e}")
        return {"stdout": "", "stderr": str(e), "returncode": 1}


def run_tests(repo_path: str, timeout: int = 60) -> dict:
    """
    Detect and run the repository's test command.
    Returns stdout, stderr, returncode, command, and skipped.
    """
    abs_path = os.path.abspath(repo_path)
    if not os.path.isdir(abs_path):
        return {
            "stdout": "",
            "stderr": f"Repository not found: {repo_path}",
            "returncode": 1,
            "command": "",
            "skipped": False,
        }

    command = _detect_test_command(abs_path)
    if not command:
        return {
            "stdout": "No test command detected.",
            "stderr": "",
            "returncode": 0,
            "command": "",
            "skipped": True,
        }

    log("TOOL", f"Running tests: {' '.join(command)}")

    try:
        result = _execute(command, abs_path, timeout)
        return {**result, "command": " ".join(command), "skipped": False}
    except subprocess.TimeoutExpired:
        log("ERROR", f"Test run timed out after {timeout}s")
        return {
            "stdout": "",
            "stderr": f"Timeout after {timeout}s",
            "returncode": -1,
            "command": " ".join(command),
            "skipped": False,
        }
    except FileNotFoundError as e:
        return {
            "stdout": "",
            "stderr": f"Test runner not found: {e.filename}",
            "returncode": 1,
            "command": " ".join(command),
            "skipped": False,
        }
    except Exception as e:
        log("ERROR", f"Test execution failed: {e}")
        return {
            "stdout": "",
            "stderr": str(e),
            "returncode": 1,
            "command": " ".join(command),
            "skipped": False,
        }


def _execute(cmd: list, cwd: str, timeout: int) -> dict:
    """Run a command and capture output."""
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=cwd, timeout=timeout
    )
    return {
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "returncode": result.returncode,
    }


def _detect_test_command(repo_path: str) -> list:
    """Detect a likely test command for common repository types."""
    package_json = os.path.join(repo_path, "package.json")
    if os.path.isfile(package_json):
        npm_cmd = _detect_npm_test_command(package_json)
        if npm_cmd:
            return npm_cmd

    if os.path.isfile(os.path.join(repo_path, "go.mod")):
        return ["go", "test", "./..."]

    if os.path.isfile(os.path.join(repo_path, "Cargo.toml")):
        return ["cargo", "test"]

    if _has_python_tests(repo_path):
        python_cmd = os.getenv("PYTHON", sys.executable or "python3")
        if _python_module_available(python_cmd, "pytest"):
            return [python_cmd, "-m", "pytest", "-q"]
        return [python_cmd, "-m", "unittest", "discover"]

    return []


def _detect_npm_test_command(package_json: str) -> list:
    """Return npm test command when package.json defines a real test script."""
    try:
        with open(package_json, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    test_script = data.get("scripts", {}).get("test", "").strip()
    if not test_script:
        return []
    if "no test specified" in test_script.lower():
        return []

    return ["npm", "test"]


def _has_python_tests(repo_path: str) -> bool:
    """Return True if the repo appears to contain Python tests or pytest config."""
    config_names = {"pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"}
    for name in config_names:
        path = os.path.join(repo_path, name)
        if not os.path.isfile(path):
            continue
        try:
            content = _read_small_file(path).lower()
        except Exception:
            content = ""
        if "pytest" in content or name == "pytest.ini":
            return True

    skip_dirs = {".git", "__pycache__", "node_modules", "venv", ".venv", "dist", "build"}
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for fname in files:
            if fname.startswith("test_") and fname.endswith(".py"):
                return True
            if fname.endswith("_test.py"):
                return True
    return False


def _read_small_file(path: str, max_chars: int = 12000) -> str:
    """Read a small prefix of a config file for test detection."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read(max_chars)


def _python_module_available(python_cmd: str, module: str) -> bool:
    """Check if a module can be imported by the selected Python runtime."""
    try:
        result = subprocess.run(
            [python_cmd, "-c", f"import {module}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _compile_and_run_c(filepath: str, cwd: str, ext: str, timeout: int) -> dict:
    """Compile and run C/C++ files."""
    out_bin = os.path.join(cwd, "a.out")
    compiler = "gcc" if ext == ".c" else "g++"

    compile_result = subprocess.run(
        [compiler, filepath, "-o", out_bin],
        capture_output=True, text=True, cwd=cwd, timeout=timeout
    )
    if compile_result.returncode != 0:
        return {
            "stdout": "",
            "stderr": f"Compilation failed:\n{compile_result.stderr.strip()}",
            "returncode": compile_result.returncode,
        }

    result = _execute([out_bin], cwd, timeout)

    try:
        os.remove(out_bin)
    except OSError:
        pass

    return result


def _compile_and_run_java(filepath: str, cwd: str, classname: str, timeout: int) -> dict:
    """Compile and run Java files."""
    compile_result = subprocess.run(
        ["javac", filepath],
        capture_output=True, text=True, cwd=cwd, timeout=timeout
    )
    if compile_result.returncode != 0:
        return {
            "stdout": "",
            "stderr": f"Compilation failed:\n{compile_result.stderr.strip()}",
            "returncode": compile_result.returncode,
        }

    result = _execute(["java", "-cp", cwd, classname], cwd, timeout)

    class_file = os.path.join(cwd, classname + ".class")
    try:
        os.remove(class_file)
    except OSError:
        pass

    return result
