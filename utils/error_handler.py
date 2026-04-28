"""
AI Code Agent — Error Handler
Parses executor output to detect common Python errors and suggest fixes.
"""

import re


# ─── Suggestion Helpers ──────────────────────────────────────

def _suggest_syntax(message: str) -> str:
    msg = message.lower()
    if "unexpected eof" in msg or "unexpected end" in msg:
        return "Unexpected end of file — likely a missing closing bracket, parenthesis, or quote."
    if "invalid syntax" in msg:
        return "Invalid syntax — check for missing colons after if/for/def/class, unmatched brackets, or stray characters."
    if "cannot assign" in msg:
        return "Assignment to a literal or expression — check the left-hand side of the assignment."
    return f"Syntax error: {message}. Review the flagged line and the line above it."


def _suggest_import(message: str) -> str:
    msg = message.lower()
    if "no module named" in msg:
        # Extract module name
        match = re.search(r"no module named ['\"]?([a-zA-Z0-9_.\-]+)['\"]?", msg)
        name = match.group(1) if match else "the module"
        return (
            f"Module '{name}' not found. "
            f"Install it with: pip install {name.split('.')[0]}  "
            f"— or check that the file exists in the repo and the path is correct."
        )
    if "cannot import name" in msg:
        return "Name not found in module — check spelling, or the function/class may have been renamed or removed."
    return f"Import failed: {message}. Verify the module name and that it is installed."


def _suggest_name(message: str) -> str:
    match = re.search(r"name ['\"](.+?)['\"] is not defined", message, re.IGNORECASE)
    if match:
        name = match.group(1)
        return (
            f"'{name}' is not defined. "
            "Check: (1) spelling, (2) the variable is assigned before use, "
            "(3) it is imported at the top of the file."
        )
    return f"Name not defined: {message}. Check variable scope and spelling."


def _suggest_type(message: str) -> str:
    msg = message.lower()
    if "takes" in msg and "argument" in msg:
        return "Wrong number of arguments passed to a function. Check the function signature and the call site."
    if "unsupported operand" in msg:
        return "Operation applied to incompatible types (e.g. str + int). Add explicit type conversion."
    if "not callable" in msg:
        return "Attempted to call something that is not a function. Check if the variable was accidentally overwritten."
    if "must be str" in msg or "must be int" in msg:
        return "Wrong type passed. Add explicit conversion: str(), int(), or float() as appropriate."
    return f"Type mismatch: {message}. Verify argument types match the function's expectations."


# ─── Error Patterns ─────────────────────────────────────────
# Each entry: (error_type_label, compiled_regex, suggest_fn)

_PATTERNS = [
    (
        "SyntaxError",
        re.compile(r"SyntaxError:\s*(.+)", re.IGNORECASE),
        _suggest_syntax,
    ),
    (
        "IndentationError",
        re.compile(r"IndentationError:\s*(.+)", re.IGNORECASE),
        lambda m: "Fix indentation — use 4 spaces consistently, no mixed tabs/spaces.",
    ),
    (
        "ImportError",
        re.compile(r"(?:ImportError|ModuleNotFoundError):\s*(.+)", re.IGNORECASE),
        _suggest_import,
    ),
    (
        "NameError",
        re.compile(r"NameError:\s*(.+)", re.IGNORECASE),
        _suggest_name,
    ),
    (
        "TypeError",
        re.compile(r"TypeError:\s*(.+)", re.IGNORECASE),
        _suggest_type,
    ),
    (
        "AttributeError",
        re.compile(r"AttributeError:\s*(.+)", re.IGNORECASE),
        lambda m: f"Object does not have that attribute. Check spelling or verify the object type. Detail: {m}",
    ),
    (
        "ValueError",
        re.compile(r"ValueError:\s*(.+)", re.IGNORECASE),
        lambda m: f"Invalid value passed to a function. Check inputs and types. Detail: {m}",
    ),
    (
        "IndexError",
        re.compile(r"IndexError:\s*(.+)", re.IGNORECASE),
        lambda m: "List index out of range. Check loop bounds and list length before accessing.",
    ),
    (
        "KeyError",
        re.compile(r"KeyError:\s*(.+)", re.IGNORECASE),
        lambda m: f"Dict key not found: {m}. Use .get() or check key existence with `in`.",
    ),
    (
        "FileNotFoundError",
        re.compile(r"FileNotFoundError:\s*(.+)", re.IGNORECASE),
        lambda m: "File not found. Verify the path is correct and relative to the repo root.",
    ),
    (
        "RecursionError",
        re.compile(r"RecursionError:\s*(.+)", re.IGNORECASE),
        lambda m: "Infinite recursion detected. Add a base case or check termination condition.",
    ),
    (
        "ZeroDivisionError",
        re.compile(r"ZeroDivisionError:\s*(.+)", re.IGNORECASE),
        lambda m: "Division by zero. Add a guard: `if denominator != 0` before dividing.",
    ),
]


# ─── Public API ─────────────────────────────────────────────

def analyze_error(output: str) -> dict:
    """
    Parse executor output (stdout + stderr) and identify the error.

    Returns:
        {
            "type":       str,   # error class name, or "Unknown"
            "message":    str,   # raw error message extracted
            "suggestion": str,   # actionable fix hint
        }

    Returns type="None" if no error is detected.
    """
    if not output:
        return {"type": "None", "message": "", "suggestion": ""}

    for error_type, pattern, suggest_fn in _PATTERNS:
        match = pattern.search(output)
        if match:
            message = match.group(1).strip()
            suggestion = suggest_fn(message)
            return {
                "type":       error_type,
                "message":    message,
                "suggestion": suggestion,
            }

    # Generic fallback: non-zero return code with traceback
    if "Traceback (most recent call last)" in output:
        # Grab the last non-empty line as the raw error
        lines = [l.strip() for l in output.splitlines() if l.strip()]
        last_line = lines[-1] if lines else output[:200]
        return {
            "type":       "RuntimeError",
            "message":    last_line,
            "suggestion": "An unhandled exception occurred. Read the full traceback above to locate the failing line.",
        }

    if "Return code: 1" in output or "Return code: -1" in output:
        return {
            "type":       "ExecutionError",
            "message":    "Non-zero exit code with no traceback",
            "suggestion": "The process exited with an error. Check stderr output above for details.",
        }

    return {"type": "None", "message": "", "suggestion": ""}