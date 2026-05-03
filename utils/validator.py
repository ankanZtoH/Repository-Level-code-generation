"""
AI Code Agent — Syntax Validator
Pre-write validation: compile-check Python, bracket-check JS, etc.
Prevents broken code from being written to disk.
"""

import os
import json


def validate_syntax(content: str, filepath: str) -> tuple:
    """
    Validate syntax before writing a file.

    Returns:
        (valid: bool, error_message: str)
        If valid is True, error_message is empty.
    """
    if not content or not content.strip():
        return False, "Content is empty"

    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".py":
        return _validate_python(content)
    elif ext in (".js", ".ts", ".jsx", ".tsx"):
        return _validate_brackets(content, filepath)
    elif ext == ".json":
        return _validate_json(content)
    elif ext in (".html", ".htm"):
        return _validate_html_basic(content)
    elif ext in (".c", ".cpp", ".h", ".hpp", ".java"):
        return _validate_brackets(content, filepath)

    # Other languages: no validation, assume OK
    return True, ""


def _validate_python(content: str) -> tuple:
    """Validate Python syntax using compile()."""
    try:
        compile(content, "<agent-edit>", "exec")
        return True, ""
    except SyntaxError as e:
        line_info = f" at line {e.lineno}" if e.lineno else ""
        return False, f"SyntaxError{line_info}: {e.msg}"
    except Exception as e:
        return False, f"Validation error: {e}"


def _validate_brackets(content: str, filepath: str) -> tuple:
    """Basic bracket/brace/paren matching for C-like languages."""
    stack = []
    pairs = {")": "(", "]": "[", "}": "{"}
    in_string = False
    string_char = None
    escape = False

    for i, ch in enumerate(content):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if in_string:
            if ch == string_char:
                in_string = False
            continue
        if ch in ("'", '"', '`'):
            in_string = True
            string_char = ch
            continue

        if ch in ("(", "[", "{"):
            stack.append(ch)
        elif ch in (")", "]", "}"):
            if not stack:
                line = content[:i].count("\n") + 1
                return False, f"Unmatched '{ch}' at line {line}"
            if stack[-1] != pairs[ch]:
                line = content[:i].count("\n") + 1
                return False, f"Mismatched '{ch}' at line {line}, expected closing for '{stack[-1]}'"
            stack.pop()

    if stack:
        return False, f"Unclosed bracket(s): {''.join(stack)}"

    return True, ""


def _validate_json(content: str) -> tuple:
    """Validate JSON syntax."""
    try:
        json.loads(content)
        return True, ""
    except json.JSONDecodeError as e:
        return False, f"JSON error at line {e.lineno}: {e.msg}"


def _validate_html_basic(content: str) -> tuple:
    """Very basic HTML validation — check for unclosed major tags."""
    # Just ensure it has basic HTML structure
    content_lower = content.lower()
    if "<html" in content_lower and "</html>" not in content_lower:
        return False, "Missing </html> closing tag"
    if "<body" in content_lower and "</body>" not in content_lower:
        return False, "Missing </body> closing tag"
    return True, ""
