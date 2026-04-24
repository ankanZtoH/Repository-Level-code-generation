"""
AI Code Agent — Code Executor
Runs code files in subprocess with output/error capture.
"""

import subprocess
import os
from utils.logger import log


# ─── Language → Command Mapping ─────────────────────────────
RUNNERS = {
    ".py":   ["python3"],
    ".js":   ["node"],
    ".java": None,          # Handled specially (compile + run)
    ".c":    None,          # Handled specially (compile + run)
    ".cpp":  None,          # Handled specially (compile + run)
    ".rb":   ["ruby"],
    ".sh":   ["bash"],
}


def run_code(filepath: str, timeout: int = 30) -> dict:
    """
    Execute a code file and return stdout, stderr, and return code.
    Supports Python, JS, Java, C, C++, Ruby, Shell.
    """
    abs_path = os.path.abspath(filepath)
    if not os.path.isfile(abs_path):
        return {"stdout": "", "stderr": f"File not found: {filepath}", "returncode": 1}

    ext = os.path.splitext(abs_path)[1].lower()
    cwd = os.path.dirname(abs_path)
    basename = os.path.basename(abs_path)
    name_no_ext = os.path.splitext(basename)[0]

    log("TOOL", f"Running {basename} ...")

    try:
        if ext in (".c", ".cpp"):
            return _compile_and_run_c(abs_path, cwd, ext, timeout)
        elif ext == ".java":
            return _compile_and_run_java(abs_path, cwd, name_no_ext, timeout)
        elif ext in RUNNERS and RUNNERS[ext]:
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


def _compile_and_run_c(filepath: str, cwd: str, ext: str, timeout: int) -> dict:
    """Compile and run C/C++ files."""
    out_bin = os.path.join(cwd, "a.out")
    compiler = "gcc" if ext == ".c" else "g++"

    # Compile
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

    # Run
    result = _execute([out_bin], cwd, timeout)

    # Cleanup
    try:
        os.remove(out_bin)
    except OSError:
        pass

    return result


def _compile_and_run_java(filepath: str, cwd: str, classname: str, timeout: int) -> dict:
    """Compile and run Java files."""
    # Compile
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

    # Run
    result = _execute(["java", "-cp", cwd, classname], cwd, timeout)

    # Cleanup .class
    class_file = os.path.join(cwd, classname + ".class")
    try:
        os.remove(class_file)
    except OSError:
        pass

    return result
