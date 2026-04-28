"""
AI Code Agent — Phase 2: Agent Loop (Controlled Semi-Autonomous)

Supports TWO workflows:

FIX workflow (existing file):
    Step 1: read_file     (understand code)
    Step 2: write_file    (fix code)
    Step 3: run_code      (verify)
    Step 4: if error -> fix again (max 3 retries)
    Step 5: if success -> DONE

CREATE workflow (new file):
    Step 1: LLM generates code -> write_file
    Step 2: run_code      (verify)
    Step 3: if error -> fix (max 3 retries)
    Step 4: if success -> DONE

NO free-form tool selection. NO skipping steps.
"""

import os
import re
from config import MAX_AGENT_STEPS, MAX_RETRIES
from utils.logger import log, separator
from utils.llm import query_llm, query_llm_json
from utils.file_ops import read_file
from phase2.analyzer import analyze_repo
from phase2.selector import select_context, build_context_prompt
from phase2.tools import execute_tool
from utils.executor import can_execute, NON_EXECUTABLE
from utils.error_handler import analyze_error


# ─── Task Classification ────────────────────────────────────

# Words that indicate creating something new
_CREATE_KEYWORDS = {
    "create", "make", "generate", "build", "write", "new",
    "implement", "add a new", "scaffold", "setup",
}

VAGUE_PATTERNS = [
    "fix all",
    "fix everything",
    "fix the code",
    "fix all code",
    "improve everything",
    "refactor all",
    "clean up everything",
    "make it better",
    "update all files",
]


def _is_vague_task(task: str) -> bool:
    """Reject vague tasks that lack a specific file or bug reference."""
    task_lower = task.strip().lower()

    for pattern in VAGUE_PATTERNS:
        if task_lower == pattern or task_lower.startswith(pattern):
            return True

    # Too short to be actionable
    if len(task_lower.split()) < 3:
        return True

    return False


def _is_create_task(task: str) -> bool:
    """Detect if the task is about creating a new file rather than fixing one."""
    task_lower = task.lower()

    # Check for create keywords at the start of the task
    for keyword in _CREATE_KEYWORDS:
        if task_lower.startswith(keyword):
            return True

    # Check for "create/make/build ... file" patterns
    create_patterns = [
        r"\b(create|make|generate|build|write)\b.*\b(file|script|program|module|page)\b",
        r"\b(new)\b.*\.(py|js|c|cpp|java|html|css)\b",
        r"\b(implement|add)\b.*\b(function|class|module)\b.*\b(new|file)\b",
    ]
    for pattern in create_patterns:
        if re.search(pattern, task_lower):
            return True

    return False


# Extension to detect from task keywords
_LANGUAGE_HINTS = {
    "python": ".py", "py": ".py",
    "javascript": ".js", "js": ".js", "node": ".js",
    "java": ".java",
    "c++": ".cpp", "cpp": ".cpp",
    "html": ".html", "webpage": ".html", "web page": ".html",
    "css": ".css", "stylesheet": ".css", "style": ".css",
}

# All supported file extensions
_ALL_SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".c", ".cpp", ".h", ".hpp",
    ".java",
    ".html", ".css", ".scss",
    ".rb", ".go", ".rs", ".sh",
}


def _detect_language_from_task(task: str) -> str:
    """Detect the target language/extension from the task description."""
    task_lower = task.lower()

    # Check for explicit file with extension in the task
    for word in task.split():
        cleaned = word.strip(".,;:\"'()[]{}")
        for ext in _ALL_SUPPORTED_EXTENSIONS:
            if cleaned.lower().endswith(ext):
                return ext

    # Check for language keywords
    for keyword, ext in _LANGUAGE_HINTS.items():
        if keyword in task_lower:
            return ext

    # Check for C language (special case — 'c' is too short for generic match)
    if re.search(r'\bc\b', task_lower) and any(w in task_lower for w in ['program', 'file', 'code', 'function']):
        return ".c"

    # Default to Python
    return ".py"


def _generate_filename(task: str) -> str:
    """
    Generate a sensible filename from a create task description.
    Detects language from task and uses appropriate extension.
    e.g. "make a python file that checks even or odd" -> "number_even_odd.py"
         "create an HTML page" -> "page.html"
         "write a C program for fibonacci" -> "fibonacci.c"
    """
    task_lower = task.lower()

    # If user explicitly names a file with extension, use it
    words = task.split()
    for word in words:
        cleaned = word.strip(".,;:\"'()[]{}")
        for ext in _ALL_SUPPORTED_EXTENSIONS:
            if cleaned.lower().endswith(ext):
                return cleaned

    # Detect language
    ext = _detect_language_from_task(task)

    # Extract meaningful words for filename
    filler = {
        "a", "an", "the", "that", "can", "which", "will", "to", "for",
        "is", "are", "it", "of", "in", "and", "or", "with", "from",
        "make", "create", "generate", "build", "write", "new",
        "python", "javascript", "java", "html", "css", "cpp",
        "file", "script", "program", "module", "code", "please", "me",
        "check", "whether", "wheather", "if", "page", "webpage",
        "stylesheet", "style", "using", "use",
    }

    key_words = []
    for word in task_lower.split():
        cleaned = re.sub(r'[^a-z0-9]', '', word)
        if cleaned and cleaned not in filler and len(cleaned) > 1:
            key_words.append(cleaned)

    if key_words:
        name = "_".join(key_words[:3])
        return f"{name}{ext}"

    # Fallback names per language
    fallback = {
        ".py": "new_script.py", ".js": "script.js", ".c": "main.c",
        ".cpp": "main.cpp", ".java": "Main.java", ".html": "index.html",
        ".css": "style.css",
    }
    return fallback.get(ext, f"new_file{ext}")


# ─── File Extraction (for fix tasks) ────────────────────────

# Unsupported extensions that should be rejected
_UNSUPPORTED_EXTENSIONS = {
    ".swift", ".kt", ".php", ".bat", ".ps1", ".r", ".m", ".sql",
    ".dart", ".lua", ".pl", ".scala",
}


def _extract_target_file(task: str, context: list) -> tuple:
    """
    Extract the target file from the task description.

    Returns:
        (filename, error_message)
        - If a supported file is found: ("calculator.py", "")
        - If an unsupported file is found: ("", "file.swift is not supported...")
        - If no file found: ("", "")  <-- Proceed to context
    """
    words = task.split()
    for word in words:
        cleaned = word.strip(".,;:\"'()[]{}")

        # Check for any supported file extension
        for ext in _ALL_SUPPORTED_EXTENSIONS:
            if cleaned.lower().endswith(ext):
                return (cleaned, "")

        # Check for unsupported extensions
        for ext in _UNSUPPORTED_EXTENSIONS:
            if cleaned.lower().endswith(ext):
                return ("", f"{cleaned} is not supported. Supported: .py, .js, .c, .cpp, .java, .html, .css")

    # No explicit file mentioned in task — check context
    if context:
        return (context[0].get("relative", ""), "")

    # No file found at all — return empty but NO error yet
    return ("", "")


# ─── Loop Protection ────────────────────────────────────────

class LoopProtector:
    """Track repeated actions and prevent infinite loops."""

    def __init__(self, max_repeats: int = 3):
        self.max_repeats = max_repeats
        self.action_history = []

    def record(self, tool: str, target: str, failed: bool):
        self.action_history.append((tool, target, failed))

    def is_stuck(self) -> bool:
        if len(self.action_history) < self.max_repeats:
            return False
        recent = self.action_history[-self.max_repeats:]
        if all(r[0] == recent[0][0] and r[1] == recent[0][1] and r[2] for r in recent):
            return True
        return False

    def suggest_recovery(self) -> str:
        if not self.action_history:
            return "search_files"
        last_tool = self.action_history[-1][0]
        if last_tool == "write_file":
            return "read_file"
        elif last_tool == "run_code":
            return "read_file"
        elif last_tool == "read_file":
            return "search_files"
        else:
            return "read_file"


# ─── Input Detection ────────────────────────────────────────

def _has_blocking_input(file_path: str, repo_path: str) -> bool:
    """Check if a Python file contains input() calls that would block execution."""
    full_path = os.path.join(repo_path, file_path) if not os.path.isabs(file_path) else file_path
    try:
        content = read_file(full_path)
        if not content:
            return False
        # Check for input() calls (not inside comments)
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "input(" in stripped:
                return True
        return False
    except Exception:
        return False


def _is_timeout_error(run_result: str) -> bool:
    """Check if a run result is a timeout error."""
    return "Timeout after" in run_result or "Return code: -1" in run_result


# ─── System Prompts ─────────────────────────────────────────

AGENT_SYSTEM_PROMPT = """You are a coding agent. You fix bugs and create code files.

RULES:
- write_file content MUST be the ENTIRE file, not just the changed part.
- Paths are relative to repo root.
- Supports: Python, C, C++, Java, JavaScript, HTML, CSS.
- For executable files (Python, C, JS, Java): include test/demo code.
- NEVER use input() or scanf(). Use hardcoded test values instead.

Respond with ONLY valid JSON.

TOOLS: read_file, write_file, run_code, search_files

Examples:
{"thought": "Read the file", "tool": "read_file", "path": "calculator.py", "done": false}
{"thought": "Fix bug", "tool": "write_file", "path": "calculator.py", "content": "def add(a, b):\\n    return a + b\\n", "done": false}
{"thought": "Verify fix", "tool": "run_code", "path": "calculator.py", "done": false}
{"thought": "Fix works", "tool": "", "done": true, "summary": "Fixed the add function"}"""

CREATE_SYSTEM_PROMPT = """You are a coding agent. You create new code files.

RULES:
- The "content" field MUST be the COMPLETE, working file.
- For Python: include if __name__ == "__main__": block.
- For C/C++: include a main() function with printf output.
- For Java: include a main method with System.out.println output.
- For JavaScript: include console.log output at the end.
- For HTML: write a complete valid HTML5 document.
- For CSS: write valid CSS with comments.
- NEVER use input()/scanf()/prompt(). Use hardcoded test values.
- Write clean, well-documented code.

Respond with ONLY valid JSON:
{"thought": "...", "tool": "write_file", "path": "FILENAME.ext", "content": "FULL_FILE_CONTENT", "done": false}"""


# ─── Entry Point ────────────────────────────────────────────

def run_agent(task: str, repo_path: str) -> dict:
    """
    Run the controlled semi-autonomous agent pipeline.

    Detects task type:
      - CREATE task -> generate new file, write, run, verify
      - FIX task    -> read existing file, fix, run, verify

    Returns: {"success": bool, "summary": str, "steps": int}
    """
    print(f"\n--- AGENT START ---")
    print(f"Task: {task}")

    # ── Validate task ──
    if _is_vague_task(task):
        print(f"REJECTED: Task is too vague.")
        print(f"Provide a specific file or bug, e.g.: 'Fix bug in calculator.py'")
        return {
            "success": False,
            "summary": "Task rejected: too vague. Specify a file or specific bug.",
            "steps": 0,
        }

    abs_repo = os.path.abspath(repo_path)

    # ── Detect task type ──
    if _is_create_task(task):
        print("Mode: CREATE")
        return _execute_create_workflow(task, abs_repo)

    # ── FIX workflow ──
    print("Mode: FIX")

    # Analyze repo (Python only)
    repo_analysis = analyze_repo(abs_repo)
    py_files = repo_analysis.get("files", [])

    if not py_files:
        print("ERROR: No Python files found in repository")
        return {
            "success": False,
            "summary": "No Python files found in repository",
            "steps": 0,
        }

    # Check for non-Python file references BEFORE context selection
    target_file, file_error = _extract_target_file(task, [])

    if file_error:
        print(f"REJECTED: {file_error}")
        return {
            "success": False,
            "summary": file_error,
            "steps": 0,
        }

    # Select context
    context = select_context(task, repo_analysis)

    # If no file was found in the task, try context
    if not target_file:
        target_file, file_error = _extract_target_file(task, context)
        if file_error or not target_file:
            msg = file_error or "Could not determine target Python file from task."
            print(f"ERROR: {msg}")
            return {
                "success": False,
                "summary": msg,
                "steps": 0,
            }

    print(f"Target: {target_file}")

    # Execute fix workflow
    return _execute_fix_workflow(task, target_file, context, abs_repo)


# ─── CREATE Workflow ────────────────────────────────────────

def _execute_create_workflow(task: str, repo_path: str) -> dict:
    """
    Create a new Python file:
      1. Generate filename from task
      2. Ask LLM to generate code -> write_file
      3. run_code to verify
      4. if error -> fix (max retries)
      5. if success -> DONE
    """
    loop_guard = LoopProtector(max_repeats=MAX_RETRIES)
    step_count = 0

    # Step 1: Generate filename
    target_file = _generate_filename(task)
    print(f"Target: {target_file}")

    # Step 2: Ask LLM to generate the file
    step_count += 1
    print(f"\nSTEP {step_count}: write_file {target_file}")

    create_prompt = _build_create_prompt(task, target_file)
    response = query_llm_json(create_prompt, system_prompt=CREATE_SYSTEM_PROMPT)

    if not response:
        print("ERROR: LLM returned empty response")
        return {"success": False, "summary": "LLM failed to generate code", "steps": step_count}

    new_content = response.get("content", "")
    if not new_content:
        print("ERROR: LLM did not provide file content")
        return {"success": False, "summary": "LLM did not generate file content", "steps": step_count}

    # Use the filename from LLM if it provided one (and it's .py)
    llm_path = response.get("path", "")
    if llm_path and llm_path.endswith(".py"):
        target_file = llm_path

    # Write the file
    write_action = {"tool": "write_file", "path": target_file, "content": new_content}
    write_result = execute_tool(write_action, repo_path)

    if write_result.startswith("Error"):
        print(f"  {write_result}")
        return {"success": False, "summary": f"Failed to write {target_file}", "steps": step_count}

    print(f"  Created {target_file}")

    # Step 3: Run the code to verify (if executable)
    if not can_execute(target_file):
        summary = response.get("thought", f"Created {target_file}")
        print(f"  Note: {target_file} is not executable (e.g. HTML/CSS). Skipping run step.")
        print(f"\nDONE: {summary}")
        return {"success": True, "summary": summary, "steps": step_count}

    step_count += 1
    print(f"STEP {step_count}: run_code {target_file}")

    run_action = {"tool": "run_code", "path": target_file}
    run_result = execute_tool(run_action, repo_path)

    print(f"  {run_result[:300]}")

    if "Return code: 0" in run_result:
        summary = response.get("thought", f"Created {target_file}")
        print(f"\nReturn code: 0")
        print(f"\nDONE: {summary}")
        return {"success": True, "summary": summary, "steps": step_count}

    # Handle timeout caused by input() — the file is valid, just interactive
    if _is_timeout_error(run_result) and _has_blocking_input(target_file, repo_path):
        print(f"  Note: File uses input() which blocks automated execution.")
        print(f"  The file was created successfully but requires user input to run.")
        print(f"\nDONE: Created {target_file} (interactive — uses input())")
        return {"success": True, "summary": f"Created {target_file} (uses input, runs interactively)", "steps": step_count}

    # Step 4+: Fix errors in the generated file
    last_error = run_result
    loop_guard.record("run_code", target_file, True)

    for retry in range(1, MAX_RETRIES + 1):
        if loop_guard.is_stuck():
            loop_guard = LoopProtector(max_repeats=MAX_RETRIES)

        # Re-read current file
        step_count += 1
        print(f"\nSTEP {step_count}: read_file {target_file}")
        read_action = {"tool": "read_file", "path": target_file}
        observation = execute_tool(read_action, repo_path)
        file_content = observation
        if observation.startswith("[File:"):
            newline_idx = observation.find("\n")
            if newline_idx != -1:
                file_content = observation[newline_idx + 1:]

        # Ask LLM to fix
        step_count += 1
        print(f"STEP {step_count}: write_file {target_file}")

        fix_prompt = _build_fix_prompt(task, target_file, file_content, last_error)
        response = query_llm_json(fix_prompt, system_prompt=AGENT_SYSTEM_PROMPT)

        if not response or not response.get("content"):
            loop_guard.record("write_file", target_file, True)
            continue

        new_content = response.get("content", "")
        write_action = {"tool": "write_file", "path": target_file, "content": new_content}
        write_result = execute_tool(write_action, repo_path)

        if write_result.startswith("Error"):
            loop_guard.record("write_file", target_file, True)
            continue

        # Run again
        step_count += 1
        print(f"STEP {step_count}: run_code {target_file}")
        run_action = {"tool": "run_code", "path": target_file}
        run_result = execute_tool(run_action, repo_path)
        print(f"  {run_result[:300]}")

        if "Return code: 0" in run_result:
            summary = f"Created {target_file}"
            print(f"\nReturn code: 0")
            print(f"\nDONE: {summary}")
            return {"success": True, "summary": summary, "steps": step_count}

        error_info = analyze_error(run_result)
        last_error = run_result
        loop_guard.record("run_code", target_file, True)
        print(f"  Retry {retry}/{MAX_RETRIES}: {error_info.get('type', 'Error')}")

    print(f"\nFAILED: Could not create working file after {MAX_RETRIES} retries")
    return {
        "success": False,
        "summary": f"Failed to create working {target_file} after {MAX_RETRIES} retries",
        "steps": step_count,
    }


# ─── FIX Workflow ───────────────────────────────────────────

def _execute_fix_workflow(task: str, target_file: str, context: list, repo_path: str) -> dict:
    """
    Fix an existing file:
      1. read_file
      2. run_code (to get error/traceback)
      3. LLM generates fix (using error) -> write_file
      4. run_code (verify)
      5. if error -> retry fix (max MAX_RETRIES times)
      6. if success -> DONE
    """
    loop_guard = LoopProtector(max_repeats=MAX_RETRIES)
    step_count = 0
    file_content = ""
    last_error = ""

    # ── Step 1: Read the target file ──
    step_count += 1
    print(f"\nSTEP {step_count}: read_file {target_file}")

    read_action = {"tool": "read_file", "path": target_file}
    observation = execute_tool(read_action, repo_path)

    if observation.startswith("Error:"):
        # File not found — try search
        step_count += 1
        print(f"STEP {step_count}: search_files {target_file}")

        base_name = os.path.splitext(os.path.basename(target_file))[0]
        search_action = {"tool": "search_files", "directory": repo_path, "query": base_name}
        search_result = execute_tool(search_action, repo_path)
        print(f"  {search_result[:200]}")

        read_action = {"tool": "read_file", "path": target_file}
        observation = execute_tool(read_action, repo_path)

        if observation.startswith("Error:"):
            print(f"ERROR: Cannot read {target_file}")
            return {"success": False, "summary": f"Cannot read {target_file}", "steps": step_count}

    # Extract file content
    file_content = observation
    if observation.startswith("[File:"):
        newline_idx = observation.find("\n")
        if newline_idx != -1:
            file_content = observation[newline_idx + 1:]

    # ── Step 2: Run the code to get an initial error ──
    if can_execute(target_file):
        step_count += 1
        print(f"STEP {step_count}: run_code {target_file} (initial check)")
        run_result = execute_tool({"tool": "run_code", "path": target_file}, repo_path)
        
        if "Return code: 0" not in run_result:
            last_error = run_result
            print(f"  Detected error: {analyze_error(run_result).get('type', 'Error')}")
        else:
            print("  Initial run succeeded (no errors detected yet)")

    # ── Step 3: Ask LLM to generate the fix ──
    step_count += 1
    print(f"STEP {step_count}: write_file {target_file}")

    fix_prompt = _build_fix_prompt(task, target_file, file_content, last_error)
    response = query_llm_json(fix_prompt, system_prompt=AGENT_SYSTEM_PROMPT)

    if not response:
        print("ERROR: LLM returned empty response")
        return {"success": False, "summary": "LLM failed to generate fix", "steps": step_count}

    new_content = response.get("content", "")
    if not new_content:
        if response.get("done", False):
            summary = response.get("summary", "No changes needed")
            print(f"\nDONE: {summary}")
            return {"success": True, "summary": summary, "steps": step_count}
        print("ERROR: LLM did not provide file content")
        return {"success": False, "summary": "LLM did not provide file content", "steps": step_count}

    # ── Safety Check: Deletion Protection ──
    # If the new content is much shorter than the original (e.g. < 60% of original)
    # and the task wasn't explicitly to delete code, it's likely a lazy LLM.
    if len(file_content) > 100 and len(new_content) < (len(file_content) * 0.6):
        msg = "Refusing to write: New content is significantly shorter than original. LLM likely omitted parts of the file."
        print(f"  [WARNING] Deletion detected ({len(new_content)} vs {len(file_content)} chars)")
        
        # Force a retry with a specific warning
        step_count += 1
        print(f"STEP {step_count}: write_file {target_file} (RETRY - No Deletions Allowed)")
        warning_prompt = f"{fix_prompt}\n\nCRITICAL ERROR: Your previous response deleted most of the file. You MUST provide the ENTIRE file content in the 'content' field, including all existing functions. Do NOT omit anything."
        response = query_llm_json(warning_prompt, system_prompt=AGENT_SYSTEM_PROMPT)
        new_content = response.get("content", "") if response else ""
        
        if not new_content or len(new_content) < (len(file_content) * 0.6):
            return {"success": False, "summary": "LLM repeatedly deleted file content", "steps": step_count}

    write_action = {"tool": "write_file", "path": target_file, "content": new_content}
    write_result = execute_tool(write_action, repo_path)

    if write_result.startswith("Error"):
        print(f"  {write_result}")
        return {"success": False, "summary": f"Failed to write {target_file}", "steps": step_count}

    # ── Step 4: Run the code to verify ──
    if can_execute(target_file):
        step_count += 1
        print(f"STEP {step_count}: run_code {target_file} (verify)")

        run_action = {"tool": "run_code", "path": target_file}
        run_result = execute_tool(run_action, repo_path)

        print(f"  {run_result[:300]}")

        if "Return code: 0" in run_result:
            summary = response.get("thought", response.get("summary", "Fixed the code"))
            print(f"\nReturn code: 0")
            print(f"\nDONE: {summary}")
            return {"success": True, "summary": summary, "steps": step_count}
        
        last_error = run_result
    else:
        # Non-executable success
        summary = response.get("thought", "Updated file")
        print(f"\nDONE: {summary}")
        return {"success": True, "summary": summary, "steps": step_count}

    # ── Step 4+: Retry loop on failure ──
    error_info = analyze_error(run_result)
    last_error = run_result
    loop_guard.record("run_code", target_file, True)

    for retry in range(1, MAX_RETRIES + 1):
        if loop_guard.is_stuck():
            recovery = loop_guard.suggest_recovery()
            print(f"LOOP DETECTED: Forcing {recovery}")

            if recovery == "read_file":
                step_count += 1
                print(f"STEP {step_count}: read_file {target_file}")
                read_action = {"tool": "read_file", "path": target_file}
                observation = execute_tool(read_action, repo_path)
                if observation.startswith("[File:"):
                    newline_idx = observation.find("\n")
                    if newline_idx != -1:
                        file_content = observation[newline_idx + 1:]
            elif recovery == "search_files":
                step_count += 1
                print(f"STEP {step_count}: search_files for error context")
                search_term = error_info.get("message", "error")[:30]
                search_action = {"tool": "search_files", "directory": repo_path, "query": search_term}
                execute_tool(search_action, repo_path)

            loop_guard = LoopProtector(max_repeats=MAX_RETRIES)

        # Re-read current file state
        step_count += 1
        print(f"\nSTEP {step_count}: read_file {target_file}")
        read_action = {"tool": "read_file", "path": target_file}
        observation = execute_tool(read_action, repo_path)
        if observation.startswith("[File:"):
            newline_idx = observation.find("\n")
            if newline_idx != -1:
                file_content = observation[newline_idx + 1:]

        # Ask LLM to fix the error
        step_count += 1
        print(f"STEP {step_count}: write_file {target_file}")

        fix_prompt = _build_fix_prompt(task, target_file, file_content, last_error)
        response = query_llm_json(fix_prompt, system_prompt=AGENT_SYSTEM_PROMPT)

        if not response or not response.get("content"):
            loop_guard.record("write_file", target_file, True)
            continue

        new_content = response.get("content", "")
        write_action = {"tool": "write_file", "path": target_file, "content": new_content}
        write_result = execute_tool(write_action, repo_path)

        if write_result.startswith("Error"):
            loop_guard.record("write_file", target_file, True)
            continue

        # Run again
        step_count += 1
        print(f"STEP {step_count}: run_code {target_file}")

        run_action = {"tool": "run_code", "path": target_file}
        run_result = execute_tool(run_action, repo_path)
        print(f"  {run_result[:300]}")

        if "Return code: 0" in run_result:
            summary = response.get("thought", response.get("summary", "Fixed the code"))
            print(f"\nReturn code: 0")
            print(f"\nDONE: {summary}")
            return {"success": True, "summary": summary, "steps": step_count}

        error_info = analyze_error(run_result)
        last_error = run_result
        loop_guard.record("run_code", target_file, True)
        print(f"  Retry {retry}/{MAX_RETRIES}: {error_info.get('type', 'Error')}")

    print(f"\nFAILED: Could not fix after {MAX_RETRIES} retries")
    return {
        "success": False,
        "summary": f"Failed to fix {target_file} after {MAX_RETRIES} retries",
        "steps": step_count,
    }


# ─── Prompt Builders (Minimal) ──────────────────────────────

def _build_fix_prompt(task: str, target_file: str, file_content: str, last_error: str = "") -> str:
    """
    Build a minimal prompt for fixing an existing file.
    Contains ONLY: task, file content, last error (if any).
    """
    error_section = ""
    if last_error:
        error_short = last_error[-300:].replace("\n", " ")
        error_section = f"\nLast error:\n{error_short}\n\nFix the error above."

    return f"""Task: {task}

File: {target_file}
```python
{file_content}
```
{error_section}
Respond with JSON containing the ENTIRE fixed file:
{{"thought": "...", "tool": "write_file", "path": "{target_file}", "content": "ENTIRE_FILE_HERE", "done": false}}

If no fix is needed:
{{"thought": "...", "tool": "", "done": true, "summary": "..."}}"""


def _build_create_prompt(task: str, target_file: str) -> str:
    """
    Build a minimal prompt for creating a new Python file.
    """
    return f"""Task: {task}

Create a Python file named: {target_file}

Requirements:
- Write COMPLETE, working Python code
- Include a if __name__ == "__main__": block that demonstrates the code
- Do NOT use input(). Use hardcoded test values to demonstrate.
- The file must run without errors and print results

Respond with JSON:
{{"thought": "...", "tool": "write_file", "path": "{target_file}", "content": "ENTIRE_FILE_CONTENT_HERE", "done": false}}"""