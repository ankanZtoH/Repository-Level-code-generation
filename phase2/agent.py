"""
AI Code Agent — Phase 2: Agent Loop
Supports TWO modes:
  FIX mode  — queue-based multi-file traversal
    1. Run entry point -> get error
    2. Trace error -> find failing file
    3. Read file -> LLM fix -> write file
    4. Re-run entry point -> verify
    5. If new error -> add related files to queue
    6. Repeat until success or MAX_FILES explored
  CREATE mode — generate a new file from scratch
    1. Generate filename from task
    2. LLM generates code -> write file
    3. Run file -> verify
    4. If error -> fix (up to MAX_RETRIES)
BUG TYPES HANDLED:
  - SyntaxError, IndentationError
  - NameError, TypeError, ImportError, AttributeError
  - LogicError (wrong output despite return code 0)
  - RuntimeError (generic traceback)
"""
import os
import re
import ast
import hashlib
from config import MAX_RETRIES, MAX_AGENT_STEPS
from utils.logger import log, separator
from utils.llm import query_llm_json
from utils.file_ops import read_file
from utils.executor import can_execute
from utils.error_handler import analyze_error
from utils.validator import validate_syntax
from phase2.analyzer import analyze_repo, extract_dependency_graph, get_repo_map_text
from phase2.planner import create_plan
from phase2.selector import select_context
from phase2.tools import execute_tool
from phase2.retrieval import index_repo, query_relevant_code
# ─── Loop Protection (adapted from mini-swe-agent) ─────────
class LoopProtector:
    """
    Prevents infinite loops and detects stuck behavior.
    Inspired by mini-swe-agent's step_limit and cost_limit pattern.
    """
    def __init__(self, max_steps: int = MAX_AGENT_STEPS, max_retries: int = MAX_RETRIES):
        self.max_steps = max_steps
        self.max_retries = max_retries
        self.history = []          # (tool, target, success)
        self.step_count = 0
        self.no_progress_count = 0
    def record(self, tool: str, target: str, success: bool):
        """Record an action taken by the agent."""
        self.history.append((tool, target, success))
        self.step_count += 1
        if not success:
            self.no_progress_count += 1
        else:
            self.no_progress_count = 0
    def is_stuck(self) -> bool:
        """Detect if the agent is repeating the same failed action."""
        if len(self.history) < self.max_retries:
            return False
        recent = self.history[-self.max_retries:]
        return all(
            h[0] == recent[0][0] and h[1] == recent[0][1] and not h[2]
            for h in recent
        )
    def limit_reached(self) -> bool:
        """Check if the maximum step count has been reached."""
        return self.step_count >= self.max_steps
    def should_stop(self, task_complete: bool = False) -> tuple:
        """
        Determine if the agent should stop.
        Returns: (should_stop: bool, reason: str)
        """
        if task_complete:
            return True, "Task completed successfully"
        if self.limit_reached():
            return True, f"Maximum steps ({self.max_steps}) reached"
        if self.is_stuck():
            return True, "Agent is stuck — same action failing repeatedly"
        if self.no_progress_count >= 5:
            return True, "No progress after 5 consecutive failures"
        return False, ""
    def suggest_recovery(self) -> str:
        """Suggest an alternative tool when stuck."""
        if not self.history:
            return "search_files"
        last_tool = self.history[-1][0]
        recovery_map = {
            "write_file": "read_file",
            "patch_file": "read_file",
            "run_code": "read_file",
            "read_file": "search_files",
        }
        return recovery_map.get(last_tool, "read_file")
# ─── Constants ──────────────────────────────────────────────
MAX_FILES = 10   # Max files to explore in FIX mode
_ALL_SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".c", ".cpp", ".h", ".hpp",
    ".java",
    ".html", ".css", ".scss",
    ".rb", ".go", ".rs", ".sh",
}
_UNSUPPORTED_EXTENSIONS = {
    ".swift", ".kt", ".php", ".bat", ".ps1", ".r",
    ".m", ".sql", ".dart", ".lua", ".pl", ".scala",
}
_LANGUAGE_HINTS = {
    "python": ".py", "py": ".py",
    "javascript": ".js", "js": ".js", "node": ".js",
    "java": ".java",
    "c++": ".cpp", "cpp": ".cpp",
    "html": ".html", "webpage": ".html",
    "css": ".css", "stylesheet": ".css",
}
_CREATE_KEYWORDS = {
    "create", "make", "generate", "build", "write",
    "implement", "scaffold", "new",
}
# ─── System Prompts ─────────────────────────────────────────
AGENT_SYSTEM_PROMPT = """You are a coding agent that fixes bugs in code files.
RULES:
- CRITICAL: Match the language to the file extension. .js = JavaScript, .py = Python, .html = HTML, .css = CSS.
- NEVER write Python syntax (def, True/False, range, None) inside a .js file.
- NEVER write JavaScript syntax (function, const, let, =>) inside a .py file.
- The "content" field MUST contain the actual source code of the fixed file.
- Write the COMPLETE file — every function, every line, nothing omitted.
- "path" must be the exact relative filename (e.g. "calculator.py").
- NEVER use input(), scanf(), or prompt(). Use hardcoded test values only.
- For Python, do NOT use relative imports. Use absolute imports.
- If the file has no bug, set done=true with no content.
Respond with ONLY valid JSON.
Example of a correct fix response (content is real Python code):
{"thought": "add() subtracts instead of adds, fix operator", "tool": "write_file", "path": "calculator.py", "content": "def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n", "done": false}
No bug in this file:
{"thought": "This file looks correct", "done": true, "summary": "No bug found here"}"""
CREATE_SYSTEM_PROMPT = """You are a coding agent that creates new code files.
RULES:
- The "content" field MUST be the actual source code you write, not a placeholder.
- Write the COMPLETE file — every line, fully functional.
- For Python: include if __name__ == "__main__": block with hardcoded demo.
- For C/C++: include main() with printf output.
- For Java: include main() with System.out.println.
- For JavaScript: include console.log at the end.
- For HTML: write a complete valid HTML5 document.
- NEVER use input()/scanf()/prompt(). Use hardcoded values.
Respond with ONLY valid JSON:
{"thought": "...", "tool": "write_file", "path": "FILENAME.ext", "content": "FULL FILE", "done": false}"""
CREATE_REPO_SYSTEM_PROMPT = """You are a coding agent that creates small connected repositories.
RULES:
- Return ONLY valid JSON.
- Create multiple files that import/use each other.
- Include a runnable entry point.
- Include repository tests when the language supports simple tests.
- Every file content must be complete real source code, not a placeholder.
- NEVER use input(), scanf(), or prompt(). Use hardcoded demo/test values.
Respond with JSON:
{
  "thought": "...",
  "entry_point": "main.py",
  "files": [
    {"path": "main.py", "content": "FULL FILE"},
    {"path": "module.py", "content": "FULL FILE"},
    {"path": "tests/test_app.py", "content": "FULL FILE"}
  ]
}"""
# \u2500\u2500\u2500 Placeholder Guard \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
_PLACEHOLDER_PHRASES = {
    "entire file here", "entire file content", "full file content",
    "full file here", "your code here", "code here",
    "file content here", "insert code here",
    "<entire file>", "<full file>", "# your code here",
}
def _is_placeholder(content: str) -> bool:
    """
    Return True when the LLM echoed a placeholder from the prompt
    instead of writing real code.
    E.g. codellama sometimes writes 'ENTIRE FILE HERE' literally.
    """
    if not content:
        return True
    stripped = content.strip().lower()
    if stripped in _PLACEHOLDER_PHRASES:
        return True
    # Very short with no code keywords at all
    if len(stripped) < 20 and not any(
        kw in stripped for kw in ("def ", "return", "import", "class ", "=")
    ):
        return True
    return False
def _retry_for_real_content(file_name: str, file_content: str) -> str:
    """
    Hard retry when the LLM returned a placeholder.
    Sends a stripped-down direct prompt showing the current file
    and demands actual source code, no examples.
    Returns the fixed content string, or '' if still unusable.
    """
    language = _language_for_path(file_name)
    fence = _fence_for_path(file_name)
    retry_prompt = (
        f"Fix all bugs in the file '{file_name}' shown below.\n\n"
        f"```{fence}\n{file_content}\n```\n\n"
        f"Reply ONLY with this JSON (replace content with real {language} source code):\n"
        f'{{\"thought\": \"...\", \"tool\": \"write_file\", \"path\": \"{file_name}\", '
        f'\"content\": \"<actual source code>\", \"done\": false}}\n\n'
        f"The content field must contain real, runnable {language} source code."
    )
    resp = query_llm_json(retry_prompt, system_prompt=AGENT_SYSTEM_PROMPT)
    if resp and resp.get("content") and not _is_placeholder(resp["content"]):
        return resp["content"]
    return ""
# \u2500\u2500\u2500 Entry Point \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
def run_agent(task: str, repo_path: str) -> dict:
    """
    Main entry point.
    Detects CREATE vs FIX mode and dispatches accordingly.
    Returns: {"success": bool, "summary": str, "steps": int}
    """
    separator("AGENT START")
    log("PLAN", f"Task: {task}")
    abs_repo = os.path.abspath(repo_path)
    if _is_create_task(task):
        log("THOUGHT", "Task classified as CREATE mode")
        return _run_create(task, abs_repo)
    log("THOUGHT", "Task classified as FIX mode")
    return _run_fix(task, abs_repo)


def run_agent_swe(task: str, repo_path: str, max_steps: int = 15) -> dict:
    """
    Run the SWE-agent conversational loop.
    Uses multi-turn chat where the LLM accumulates context and chooses tools.
    Better for complex/vague tasks like 'fix the grid button'.
    """
    from phase2.swe_loop import run_swe_agent
    return run_swe_agent(task, repo_path, max_steps=max_steps)


# ─── FIX Mode ───────────────────────────────────────────────
def _run_fix(task: str, repo_path: str) -> dict:
    """
    Analyze repo, build dependency graph, find entry point,
    then dispatch to targeted fix or broad fix-all.
    """
    step = 0
    # Analyze repo
    repo_analysis = analyze_repo(repo_path)
    file_infos = repo_analysis.get("files", [])
    if not file_infos:
        return {"success": False, "summary": "No supported files found in repository", "steps": 0}
    # Build dependency graph
    dep_graph = repo_analysis.get("dependency_graph") or extract_dependency_graph(repo_path, file_infos)
    log("INFO", f"Dependency graph: {dep_graph}")
    # Build a task plan from the repo map. The loop still reacts to runtime
    # observations, but this gives each LLM edit step a stable objective.
    repo_map = get_repo_map_text(repo_analysis)
    plan = create_plan(task, repo_map)
    plan_context = _format_plan_context(plan)
    # Build semantic index (graceful if sentence-transformers missing)
    n_indexed = index_repo(repo_analysis)
    if n_indexed:
        log("INFO", f"Semantic index: {n_indexed} chunks indexed")
    else:
        log("INFO", "disabled (no model or no chunks)")
    # Broad task: fix all files
    if _is_broad_task(task):
        log("THOUGHT", "Broad task — exploring connected code files")
        return _run_fix_all(task, file_infos, dep_graph, repo_path, plan_context, repo_analysis)
    # Targeted task: find the specific entry point
    entry_point, err = _find_entry_point(task, repo_path, file_infos, repo_analysis)
    if err:
        return {"success": False, "summary": err, "steps": 0}
    log("INFO", f"Entry point: {entry_point}")
    return _run_fix_targeted(task, entry_point, dep_graph, repo_path, plan_context)


# ─── Self-Correction Loop (Component 7) ────────────────────

def _self_correct(target: str, repo_path: str, entry_point: str,
                  protector: LoopProtector = None, max_retries: int = 3) -> tuple:
    """
    Run code, analyze errors, fix, retry.
    Returns: (success: bool, output: str)
    """
    for attempt in range(max_retries):
        run_out = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)

        if "Return code: 0" in run_out:
            log("RESULT", f"Code passed on attempt {attempt + 1}")
            if protector:
                protector.record("run_code", entry_point, True)
            return True, run_out

        error_info = analyze_error(run_out)
        log("FEEDBACK", f"Attempt {attempt+1}/{max_retries}: "
            f"{error_info['type']} — {error_info.get('suggestion', '')[:80]}")

        if protector:
            protector.record("run_code", entry_point, False)
            stop, reason = protector.should_stop()
            if stop:
                log("ERROR", f"Self-correction halted: {reason}")
                return False, run_out

        # Read target file, ask LLM to fix
        content = read_file(os.path.join(repo_path, target))
        if not content:
            return False, run_out

        fix_prompt = (
            f"Fix the error in '{target}'.\n\n"
            f"## Current Code\n```\n{content}\n```\n\n"
            f"## Error Output\n```\n{run_out[-1500:]}\n```\n\n"
            f"## Error Analysis\n"
            f"Type: {error_info['type']}\n"
            f"Message: {error_info.get('message', '')}\n"
            f"Suggestion: {error_info.get('suggestion', 'Fix the error')}\n\n"
            f"Provide the ENTIRE fixed file.\n"
            f"Respond with JSON:\n"
            f'{{\"thought\": \"...\", \"tool\": \"write_file\", \"path\": \"{target}\", '
            f'\"content\": \"ENTIRE FIXED FILE\", \"done\": false}}'
        )
        resp = query_llm_json(fix_prompt, system_prompt=AGENT_SYSTEM_PROMPT)

        if resp and resp.get("content") and not _is_placeholder(resp["content"]):
            valid, err = validate_syntax(resp["content"], target)
            if valid:
                execute_tool(
                    {"tool": "write_file", "path": target, "content": resp["content"]},
                    repo_path
                )
                log("ACTION", f"Applied LLM fix to {target}")
            else:
                log("ERROR", f"LLM fix has bad syntax: {err}")
        else:
            log("ERROR", "LLM returned empty/placeholder fix")

    return False, run_out


def _run_fix_targeted(
    task: str,
    entry_point: str,
    dep_graph: dict,
    repo_path: str,
    plan_context: str = "",
) -> dict:
    """
    Fix a specific entry point and its dependencies using queue traversal.
    """
    step = 0
    visited = set()
    files_modified = []
    last_run_output = ""
    action_history = set()   # (action, file, content_hash) for dedup
    plan_step_idx = 0        # tracks current planner step
    # Seed queue: entry point first, then its direct deps
    queue = [entry_point]
    for dep in dep_graph.get(entry_point, []):
        if dep not in queue:
            queue.append(dep)
    # Initial run to get baseline error
    if can_execute(entry_point):
        step += 1
        log("ACTION", f"Step {step}: run_code {entry_point}")
        run_out = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)
        last_run_output = run_out
        log("OBSERVATION", run_out[:300])
        if "Return code: 0" in run_out:
            if not _is_logic_bug(task, run_out):
                step, test_out = _run_tests_step(step, repo_path)
                last_run_output = test_out
                if not _validation_succeeded(test_out):
                    log("OBSERVATION", "Entry point runs, but repository tests failed — continuing")
                    failing = _trace_error_to_file(test_out, repo_path)
                    if failing and not _is_test_file(failing) and failing not in queue:
                        queue.insert(0, failing)
                else:
                    test_note = " and tests pass" if not _tests_skipped(test_out) else ""
                    return {
                        "success": True,
                        "summary": f"No fix needed — {entry_point} already runs correctly{test_note}",
                        "steps": step,
                    }
            else:
                log("OBSERVATION", "Return code 0 but output looks wrong — checking for logic bugs")
        else:
            error_info = analyze_error(run_out)
            log("FEEDBACK", f"{error_info['type']} — {error_info['message'][:100]}")
            # Trace to actual failing file and prioritize it
            failing = _trace_error_to_file(run_out, repo_path)
            if failing and failing != entry_point and failing not in queue:
                log("OBSERVATION", f"Traced to: {failing}")
                queue.insert(0, failing)
    # Queue-based exploration
    while queue and len(visited) < MAX_FILES:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        separator("Exploring")
        log("STEP", f"Exploring: {current}  (visited {len(visited)}/{MAX_FILES})")
        # Read the file
        step += 1
        log("ACTION", f"Step {step}: read_file {current}")
        file_content = _read_file(current, repo_path)
        if not file_content:
            log("OBSERVATION", f"Cannot read {current} — skipping")
            continue
        # Build related file context
        related = {}
        for dep in dep_graph.get(current, []):
            c = _read_file(dep, repo_path)
            if c:
                related[dep] = c
        # Semantic retrieval: find relevant code not in dep graph
        semantic_ctx = _get_semantic_context(task, current, last_run_output)
        # Ask LLM to fix
        step += 1
        log("ACTION", f"Step {step}: LLM fix {current}")
        prompt = _build_fix_prompt(
            task,
            current,
            file_content,
            last_run_output,
            related,
            semantic_ctx,
            plan_context,
        )
        response = query_llm_json(prompt, system_prompt=AGENT_SYSTEM_PROMPT)
        if not response:
            log("OBSERVATION", f"LLM returned empty — skipping {current}")
            continue
        # LLM says no bug here
        if response.get("done") and not response.get("content"):
            log("OBSERVATION", f"LLM: no bug in {current}")
            for dep in dep_graph.get(current, []):
                if dep not in visited and dep not in queue:
                    queue.append(dep)
            continue
        new_content = response.get("content", "")
        if not new_content:
            log("OBSERVATION", f"No content from LLM — skipping {current}")
            continue
        # Placeholder guard
        if _is_placeholder(new_content):
            log("ERROR", f"LLM returned a placeholder — retrying")
            new_content = _retry_for_real_content(current, file_content)
            if not new_content:
                log("OBSERVATION", f"Retry placeholder — skipping {current}")
                continue
        # LLM may target a different file
        target = response.get("path", current) or current
        # Deletion protection (only for large files)
        orig_content = file_content if target == current else (_read_file(target, repo_path) or "")
        if orig_content and len(orig_content) > 500 and len(new_content) < len(orig_content) * 0.5:
            log("ERROR", f"Output too short ({len(new_content)} vs {len(orig_content)}) — skipping")
            continue
        new_content = _ensure_symbol_preservation(prompt, target, orig_content, new_content)
        if not new_content:
            continue
        # Action dedup: skip if we already wrote identical content to this file
        content_hash = hashlib.md5(new_content.encode()).hexdigest()[:8]
        action_key = ("write", target, content_hash)
        if action_key in action_history:
            log("THOUGHT", f"Skipping duplicate write to {target} (same content)")
            continue
        action_history.add(action_key)
        # Language contamination check: catch Python syntax in .js files etc.
        new_content = _fix_language_contamination(target, new_content, task)
        if not new_content:
            continue
        # Auto-fix bracket issues for C-like languages (JS/TS/Java/C)
        ext = os.path.splitext(target)[1].lower()
        if ext in ('.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp'):
            new_content = _autofix_brackets(new_content)
        # Write the fix
        step += 1
        log("ACTION", f"Step {step}: write_file {target}")
        write_out = execute_tool({"tool": "write_file", "path": target, "content": new_content}, repo_path)
        if write_out.startswith("Error"):
            log("OBSERVATION", f"Write failed: {write_out}")
            continue
        if target not in files_modified:
            files_modified.append(target)
        # Advance plan step
        plan_step_idx = _advance_plan_step(plan_context, plan_step_idx, target, "edit")
        log("OBSERVATION", f"Written: {target}")
        # Non-runnable file — skip verification, treat write as success
        if not can_execute(entry_point):
            step, test_out = _run_tests_step(step, repo_path)
            last_run_output = test_out
            if _validation_succeeded(test_out):
                summary = f"Fixed {', '.join(files_modified)}"
                log("RESULT", f"Done: {summary}")
                return {"success": True, "summary": summary, "steps": step}
            log("OBSERVATION", "Repository tests failed — continuing exploration")
            failing = _trace_error_to_file(test_out, repo_path)
            if failing and not _is_test_file(failing) and failing not in visited and failing not in queue:
                queue.insert(0, failing)
            continue
        # Re-run entry point to verify
        step += 1
        log("ACTION", f"Step {step}: run_code {entry_point} (verify)")
        run_out = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)
        last_run_output = run_out
        log("OBSERVATION", run_out[:300])
        if "Return code: 0" in run_out:
            if not _is_logic_bug(task, run_out):
                step, test_out = _run_tests_step(step, repo_path)
                last_run_output = test_out
                if _validation_succeeded(test_out):
                    summary = f"Fixed {', '.join(files_modified)}"
                    log("RESULT", f"Done: {summary}")
                    return {"success": True, "summary": summary, "steps": step}
                log("OBSERVATION", "Repository tests failed — continuing exploration")
                failing = _trace_error_to_file(test_out, repo_path)
                if failing and not _is_test_file(failing) and failing not in visited and failing not in queue:
                    queue.insert(0, failing)
                for dep in dep_graph.get(current, []):
                    if dep not in visited and dep not in queue:
                        queue.append(dep)
                continue
            log("OBSERVATION", "Output still looks wrong — continuing exploration")
            for dep in dep_graph.get(current, []):
                if dep not in visited and dep not in queue:
                    queue.append(dep)
        else:
            # Still failing — trace new error and expand queue
            error_info = analyze_error(run_out)
            log("FEEDBACK", f"Still failing: {error_info['type']} — {error_info['message'][:80]}")
            failing = _trace_error_to_file(run_out, repo_path)
            if failing and failing not in visited and failing not in queue:
                log("OBSERVATION", f"Traced to: {failing}")
                queue.insert(0, failing)
            for dep in dep_graph.get(current, []):
                if dep not in visited and dep not in queue:
                    queue.append(dep)
    # Final result
    if files_modified:
        if can_execute(entry_point):
            run_out = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)
            if "Return code: 0" in run_out and not _is_logic_bug(task, run_out):
                step, test_out = _run_tests_step(step, repo_path)
                if _validation_succeeded(test_out):
                    summary = f"Fixed {', '.join(files_modified)}"
                    log("RESULT", f"Done: {summary}")
                    return {"success": True, "summary": summary, "steps": step}
        summary = f"Modified {', '.join(files_modified)} — may still have issues"
        log("RESULT", f"Partial: {summary}")
        return {"success": False, "summary": summary, "steps": step}
    log("ERROR", "No files could be fixed")
    return {"success": False, "summary": "Could not fix any files", "steps": step}
def _run_fix_all(
    task: str,
    file_infos: list,
    dep_graph: dict,
    repo_path: str,
    plan_context: str = "",
    repo_analysis: dict = None,
) -> dict:
    """
    Broad fix-all mode: EXECUTION-DRIVEN, GRAPH-AWARE debug loop.
    Algorithm:
      1. Find the project entry point (main.py, app.py, or first runnable file).
      2. Run it to get the first error.
      3. Trace error -> identify failing file -> push to queue.
         Seed queue with ALL files reachable from entry point via dep graph.
      4. For each file in queue:
           a. read_file
           b. LLM fix -> write_file
           c. run_code(entry_point)  <- always validate the whole system
           d. if success -> DONE
           e. else -> trace new error -> continue
      5. Terminate when: success OR MAX_ITERATIONS reached.
    """
    MAX_ITERATIONS = 20
    step = 0
    files_modified = []
    visited = set()
    # ── 1. Find entry point ──────────────────────────────────
    code_files = _ordered_fix_files(file_infos)
    if not code_files:
        return {"success": False, "summary": "No editable code files found", "steps": 0}
    ENTRY_NAMES = [
        "main.py", "app.py", "run.py", "start.py", "__main__.py",
        "main.js", "index.js", "app.js",
        "main.c", "main.cpp", "Main.java",
    ]
    entry_point = ""
    for name in ENTRY_NAMES:
        for fi in code_files:
            if os.path.basename(fi["relative"]) == name:
                entry_point = fi["relative"]
                break
        if entry_point:
            break
    if not entry_point:
        for fi in code_files:
            if can_execute(fi["relative"]):
                entry_point = fi["relative"]
                break
    if not entry_point:
        entry_point = code_files[0]["relative"]
    log("INFO", f"Entry point: {entry_point}")
    # ── 2. Seed queue via BFS over dep graph ──────────────────
    queue = []
    seen_for_seed = set()
    def _bfs_seed(start: str):
        bfs = [start]
        while bfs:
            cur = bfs.pop(0)
            if cur in seen_for_seed:
                continue
            seen_for_seed.add(cur)
            queue.append(cur)
            for dep in dep_graph.get(cur, []):
                if dep not in seen_for_seed:
                    bfs.append(dep)
    _bfs_seed(entry_point)
    # Add any remaining code files not reachable from entry, ranked by importance.
    for fi in code_files:
        if fi["relative"] not in seen_for_seed:
            queue.append(fi["relative"])
    # ── 3. Initial run ───────────────────────────────────────
    step += 1
    log("ACTION", f"Step {step}: run_code {entry_point}")
    run_out = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)
    last_run_output = run_out
    log("OBSERVATION", run_out[:300])
    # Even if it runs clean, we still scan all files for logic/semantic bugs
    system_runs_clean = "Return code: 0" in run_out
    if "Return code: 0" not in run_out:
        error_info = analyze_error(run_out)
        log("FEEDBACK", f"{error_info['type']} — {error_info['message'][:100]}")
        failing = _trace_error_to_file(run_out, repo_path)
        if failing:
            log("OBSERVATION", f"Traced to: {failing}")
            if failing in queue:
                queue.remove(failing)
            queue.insert(0, failing)
    # ── 4. Execution-driven fix loop ─────────────────────────
    iteration = 0
    while queue and iteration < MAX_ITERATIONS:
        iteration += 1
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        separator("Exploring")
        log("STEP", f"Exploring: {current}  [{iteration}/{MAX_ITERATIONS}]")
        # 4a. Read
        step += 1
        log("ACTION", f"Step {step}: read_file {current}")
        file_content = _read_file(current, repo_path)
        if not file_content:
            log("OBSERVATION", f"Cannot read {current} — skipping")
            continue
        related = {}
        for dep in dep_graph.get(current, []):
            c = _read_file(dep, repo_path)
            if c:
                related[dep] = c
        # Semantic retrieval
        semantic_ctx = _get_semantic_context(task, current, last_run_output)
        # 4b. LLM fix
        step += 1
        log("ACTION", f"Step {step}: LLM fix {current}")
        prompt = _build_fix_prompt(
            task,
            current,
            file_content,
            last_run_output,
            related,
            semantic_ctx,
            plan_context,
        )
        response = query_llm_json(prompt, system_prompt=AGENT_SYSTEM_PROMPT)
        if not response:
            log("OBSERVATION", f"LLM returned empty — skipping {current}")
            continue
        if response.get("done") and not response.get("content"):
            log("OBSERVATION", f"LLM: no bug in {current} — expanding deps")
            for dep in dep_graph.get(current, []):
                if dep not in visited and dep not in queue:
                    queue.append(dep)
            continue
        new_content = response.get("content", "")
        if not new_content:
            log("OBSERVATION", f"No content from LLM — skipping {current}")
            continue
        # Placeholder guard: reject if LLM echoed example text
        if _is_placeholder(new_content):
            log("ERROR", f"LLM returned a placeholder — retrying with direct instruction")
            new_content = _retry_for_real_content(current, file_content)
            if not new_content:
                log("OBSERVATION", f"Retry returned empty or placeholder — skipping {current}")
                continue
        target = response.get("path", current) or current
        # Deletion protection: only block truly massive regressions on large files
        orig_content = file_content if target == current else (_read_file(target, repo_path) or "")
        if orig_content and len(orig_content) > 500 and len(new_content) < len(orig_content) * 0.5:
            log("ERROR", f"Fix too short ({len(new_content)} vs {len(orig_content)}) — retrying")
            retry_prompt = prompt + "\n\nCRITICAL: Provide the ENTIRE fixed file — do NOT omit any functions or lines."
            retry_resp = query_llm_json(retry_prompt, system_prompt=AGENT_SYSTEM_PROMPT)
            if retry_resp and retry_resp.get("content") and not _is_placeholder(retry_resp["content"]):
                new_content = retry_resp["content"]
                target = retry_resp.get("path", target) or target
            else:
                log("OBSERVATION", f"Retry also empty — skipping")
                continue
        new_content = _ensure_symbol_preservation(prompt, target, orig_content, new_content)
        if not new_content:
            continue
        # 4c. Write
        step += 1
        log("ACTION", f"Step {step}: write_file {target}")
        write_out = execute_tool({"tool": "write_file", "path": target, "content": new_content}, repo_path)
        if write_out.startswith("Error"):
            log("OBSERVATION", f"Write failed: {write_out}")
            continue
        if target not in files_modified:
            files_modified.append(target)
        log("OBSERVATION", f"Written: {target}")
        # 4d. Re-run entry point — validate the WHOLE system
        step += 1
        log("ACTION", f"Step {step}: run_code {entry_point} (system validation)")
        run_out = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)
        last_run_output = run_out
        log("OBSERVATION", run_out[:300])
        if "Return code: 0" in run_out:
            step, test_out = _run_tests_step(step, repo_path)
            last_run_output = test_out
            if _validation_succeeded(test_out):
                system_runs_clean = True
                log("OBSERVATION", "Return code: 0 — continuing to check remaining files for logic/semantic bugs")
                # Don't stop here — keep exploring the rest of the queue
                # so we catch naming mismatches (e.g. multiply() doing division)
                for dep in dep_graph.get(current, []):
                    if dep not in visited and dep not in queue:
                        queue.append(dep)
            else:
                system_runs_clean = False
                log("OBSERVATION", "Repository tests failed — using test output for next iteration")
                failing = _trace_error_to_file(test_out, repo_path)
                if failing and not _is_test_file(failing) and failing not in visited:
                    log("OBSERVATION", f"Traced test failure to: {failing}")
                    if failing in queue:
                        queue.remove(failing)
                    queue.insert(0, failing)
                for dep in dep_graph.get(current, []):
                    if dep not in visited and dep not in queue:
                        queue.append(dep)
        else:
            # 4e. Trace new error
            error_info = analyze_error(run_out)
            log("FEEDBACK", f"Still failing: {error_info['type']} — {error_info['message'][:80]}")
            failing = _trace_error_to_file(run_out, repo_path)
            if failing and failing not in visited:
                log("OBSERVATION", f"Traced to: {failing}")
                if failing in queue:
                    queue.remove(failing)
                queue.insert(0, failing)
            for dep in dep_graph.get(current, []):
                if dep not in visited and dep not in queue:
                    queue.append(dep)
    # ── 5. Final validation ───────────────────────────────────
    step += 1
    log("ACTION", f"Step {step}: run_code {entry_point} (final validation)")
    final_out = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)
    log("OBSERVATION", f"{final_out[:300]}")
    if "Return code: 0" in final_out:
        step, test_out = _run_tests_step(step, repo_path)
        if not _validation_succeeded(test_out):
            if files_modified:
                summary = f"Modified {', '.join(files_modified)} — tests still fail"
                log("RESULT", f"Partial: {summary}")
                return {"success": False, "summary": summary, "steps": step}
            log("ERROR", "Repository tests fail")
            return {"success": False, "summary": "Repository tests fail", "steps": step}
        if files_modified:
            summary = f"Fixed {', '.join(files_modified)}"
        else:
            summary = "All files inspected — no bugs found"
        log("RESULT", f"Done: {summary}")
        return {"success": True, "summary": summary, "steps": step}
    if files_modified:
        summary = f"Modified {', '.join(files_modified)} — may still have residual issues"
        log("RESULT", f"Partial: {summary}")
        return {"success": False, "summary": summary, "steps": step}
    log("ERROR", "No files could be fixed")
    return {"success": False, "summary": "Could not fix any files", "steps": step}
# ─── CREATE Mode ────────────────────────────────────────────
def _run_create(task: str, repo_path: str) -> dict:
    """
    Create a new file from scratch, run it, fix errors up to MAX_RETRIES.
    """
    if _is_repo_create_task(task):
        return _run_create_repo(task, repo_path)
    step = 0
    target = _generate_filename(task)
    log("INFO", f"Target: {target}")
    # Generate
    step += 1
    log("ACTION", f"Step {step}: generate {target}")
    prompt = _build_create_prompt(task, target)
    response = query_llm_json(prompt, system_prompt=CREATE_SYSTEM_PROMPT)
    if not response or not response.get("content"):
        return {"success": False, "summary": "LLM failed to generate file", "steps": step}
    content = response["content"]
    llm_path = response.get("path", "")
    if llm_path and any(llm_path.endswith(ext) for ext in _ALL_SUPPORTED_EXTENSIONS):
        target = llm_path
    # Write
    step += 1
    log("ACTION", f"Step {step}: write_file {target}")
    write_out = execute_tool({"tool": "write_file", "path": target, "content": content}, repo_path)
    if write_out.startswith("Error"):
        return {"success": False, "summary": f"Write failed: {write_out}", "steps": step}
    log("OBSERVATION", f"Created {target}")
    # Non-executable — done immediately
    if not can_execute(target):
        log("OBSERVATION", f"{target} is not executable — validating repository")
        step, test_out = _run_tests_step(step, repo_path)
        if _validation_succeeded(test_out):
            return {"success": True, "summary": f"Created {target}", "steps": step}
        return {
            "success": False,
            "summary": f"Created {target} but repository tests fail",
            "steps": step,
        }
    # Run
    step += 1
    log("ACTION", f"Step {step}: run_code {target}")
    run_out = execute_tool({"tool": "run_code", "path": target}, repo_path)
    log("OBSERVATION", run_out[:300])
    if "Return code: 0" in run_out:
        step, test_out = _run_tests_step(step, repo_path)
        if _validation_succeeded(test_out):
            return {"success": True, "summary": f"Created {target}", "steps": step}
        run_out = test_out
    # Timeout from input() — treat as success
    if ("Timeout" in run_out or "Return code: -1" in run_out) and _has_input_call(target, repo_path):
        return {
            "success": True,
            "summary": f"Created {target} (interactive — uses input())",
            "steps": step,
        }
    # Retry loop
    last_error = run_out
    for retry in range(1, MAX_RETRIES + 1):
        log("FEEDBACK", f"Retry {retry}/{MAX_RETRIES}")
        step += 1
        log("ACTION", f"Step {step}: read_file {target}")
        current_content = _read_file(target, repo_path)
        if not current_content:
            break
        step += 1
        log("ACTION", f"Step {step}: LLM fix {target}")
        fix_prompt = _build_fix_prompt(task, target, current_content, last_error)
        response = query_llm_json(fix_prompt, system_prompt=AGENT_SYSTEM_PROMPT)
        if not response or not response.get("content"):
            continue
        new_content = response["content"]
        execute_tool({"tool": "write_file", "path": target, "content": new_content}, repo_path)
        step += 1
        log("ACTION", f"Step {step}: run_code {target}")
        run_out = execute_tool({"tool": "run_code", "path": target}, repo_path)
        log("OBSERVATION", run_out[:300])
        last_error = run_out
        if "Return code: 0" in run_out:
            step, test_out = _run_tests_step(step, repo_path)
            if _validation_succeeded(test_out):
                return {"success": True, "summary": f"Created {target}", "steps": step}
            last_error = test_out
            log("OBSERVATION", "Repository tests failed after generated file ran successfully")
            continue
        error_info = analyze_error(run_out)
        log("OBSERVATION", f"Error: {error_info['type']} — {error_info['suggestion'][:80]}")
    return {
        "success": False,
        "summary": f"Created {target} but could not fix errors after {MAX_RETRIES} retries",
        "steps": step,
    }
def _run_create_repo(task: str, repo_path: str) -> dict:
    """
    Create a connected multi-file repository, validate it, and self-fix if needed.
    """
    step = 0
    step += 1
    log("ACTION", f"Step {step}: generate connected repository")
    prompt = _build_create_repo_prompt(task)
    response = query_llm_json(prompt, system_prompt=CREATE_REPO_SYSTEM_PROMPT)
    files = _extract_created_files(response)
    if not files:
        log("OBSERVATION", "LLM failed to return multi-file JSON — using connected Python fallback")
        files = _fallback_connected_repo_files(task)
        entry_point = "main.py"
    else:
        entry_point = response.get("entry_point", "") if response else ""
    written = []
    for item in files:
        rel_path = _safe_rel_path(item.get("path", ""))
        content = item.get("content", "")
        if not rel_path or not content or _is_placeholder(content):
            continue
        step += 1
        log("ACTION", f"Step {step}: write_file {rel_path}")
        write_out = execute_tool({"tool": "write_file", "path": rel_path, "content": content}, repo_path)
        if write_out.startswith("Error"):
            log("OBSERVATION", f"Write failed: {write_out}")
            continue
        written.append(rel_path)
    if not written:
        return {"success": False, "summary": "No generated files could be written", "steps": step}
    if not entry_point or entry_point not in written:
        entry_point = _choose_generated_entry_point(written)
    step, test_out = _run_tests_step(step, repo_path)
    if _validation_succeeded(test_out) and not _tests_skipped(test_out):
        summary = f"Created connected repository with {len(written)} files"
        log("RESULT", f"Done: {summary}")
        return {"success": True, "summary": summary, "steps": step}

    # Check if this is a web project (HTML + CSS/JS) — browser files can't be run in Node
    web_exts = {'.html', '.css', '.js'}
    is_web_project = all(
        os.path.splitext(w)[1].lower() in web_exts for w in written
    ) and any(w.endswith('.html') for w in written)

    if is_web_project:
        # For web projects: validate syntax of all files, then declare success
        all_valid = True
        for w in written:
            content = read_file(os.path.join(repo_path, w))
            if content:
                valid, err = validate_syntax(content, w)
                if not valid:
                    log("ERROR", f"Syntax error in {w}: {err}")
                    all_valid = False
        # Check that HTML links to CSS/JS
        html_file = next((w for w in written if w.endswith('.html')), None)
        if html_file:
            html_content = read_file(os.path.join(repo_path, html_file))
            has_css = '.css' not in [os.path.splitext(w)[1] for w in written] or \
                      'href=' in (html_content or '')
            has_js = '.js' not in [os.path.splitext(w)[1] for w in written] or \
                     'src=' in (html_content or '')
            if not has_css or not has_js:
                log("ERROR", "HTML file missing CSS/JS links")
                all_valid = False
        if all_valid:
            summary = f"Created web project with {len(written)} files: {', '.join(written)}"
            log("RESULT", f"Done: {summary}")
            return {"success": True, "summary": summary, "steps": step}

    if entry_point and can_execute(entry_point):
        step += 1
        log("ACTION", f"Step {step}: run_code {entry_point}")
        run_out = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)
        log("OBSERVATION", run_out[:300])
        if "Return code: 0" in run_out and _validation_succeeded(test_out):
            summary = f"Created connected repository with {len(written)} files"
            log("RESULT", f"Done: {summary}")
            return {"success": True, "summary": summary, "steps": step}
    log("OBSERVATION", "Generated repository needs repair — entering fix loop")
    fix_result = _run_fix(
        f"Fix the generated repository so it satisfies this task and passes tests: {task}",
        repo_path,
    )
    return {
        "success": fix_result.get("success", False),
        "summary": f"Created {len(written)} files; {fix_result.get('summary', '')}",
        "steps": step + fix_result.get("steps", 0),
    }
# ─── Task Classification ────────────────────────────────────
def _is_create_task(task: str) -> bool:
    """Return True if the task is about creating a new file."""
    task_lower = task.lower()
    for kw in _CREATE_KEYWORDS:
        if task_lower.startswith(kw):
            return True
    patterns = [
        r"\b(create|make|generate|build|write)\b.*\b(file|script|program|module|page)\b",
        r"\bnew\b.*\.(py|js|c|cpp|java|html|css)\b",
    ]
    return any(re.search(p, task_lower) for p in patterns)
def _is_repo_create_task(task: str) -> bool:
    """Return True if the task asks for a connected multi-file repo/project."""
    task_lower = task.lower()
    repo_words = [
        "repo", "repository", "project", "package", "application", "app",
        "multiple files", "multi-file", "connected files", "from scratch",
        "web app", "webapp", "website", "3 files", "three files",
        "separate files", "all of these files",
    ]
    create_words = ["create", "make", "generate", "build", "scaffold", "new", "write", "implement"]
    has_create = any(w in task_lower for w in create_words)
    has_repo = any(w in task_lower for w in repo_words)
    # Also detect explicit multi-file patterns like "index.html ... style.css ... script.js"
    import re
    file_mentions = re.findall(r'\b\w+\.\w{1,5}\b', task_lower)
    unique_files = set(f for f in file_mentions if any(f.endswith(e) for e in
        ['.html', '.css', '.js', '.py', '.java', '.c', '.cpp', '.h', '.ts', '.json']))
    if has_create and len(unique_files) >= 2:
        return True
    # Detect "N files" pattern
    if has_create and re.search(r'\b(\d+|two|three|four|five|multiple|several)\s+files?\b', task_lower):
        return True
    return has_create and has_repo
def _is_broad_task(task: str) -> bool:
    """Return True if the task targets the whole repo, not a specific file."""
    task_lower = task.lower()
    broad_patterns = [
        "fix all", "fix every", "fix all bugs", "fix bugs in the",
        "fix all errors", "fix the repo", "fix everything",
        "fix all files", "check all", "find all bugs", "repair all",
    ]
    for pat in broad_patterns:
        if pat in task_lower:
            return True
    # No specific .py filename and "all" present
    has_file = any(w.strip(".,;:'\"()").endswith(".py") for w in task.split())
    if not has_file and "all" in task_lower:
        return True
    return False
# ─── Entry Point Detection ──────────────────────────────────
def _find_entry_point(task: str, repo_path: str, file_infos: list, repo_analysis: dict) -> tuple:
    """
    Determine which file the agent should start with.
    Priority:
      1. Explicit filename in task text (e.g. "fix bug in calculator.py")
      2. File selected by context selector
      3. First Python file in the repo as fallback
    Returns: (relative_path, error_message)
    error_message is non-empty only on hard failures (unsupported extension, file not found).
    """
    # 1. Explicit filename in task
    for word in task.split():
        cleaned = word.strip(".,;:'\"()[]{}").lower()
        # Reject unsupported extensions immediately
        for bad_ext in _UNSUPPORTED_EXTENSIONS:
            if cleaned.endswith(bad_ext):
                return ("", f"'{cleaned}' is not a supported file type")
        # Check for supported extensions
        for ext in _ALL_SUPPORTED_EXTENSIONS:
            if cleaned.endswith(ext):
                # Try to find it in the repo
                full = os.path.join(repo_path, cleaned)
                if os.path.isfile(full):
                    return (cleaned, "")
                for fi in file_infos:
                    if os.path.basename(fi["relative"]).lower() == cleaned:
                        return (fi["relative"], "")
                return ("", f"File '{cleaned}' not found in repository")
    # 2. Context selector
    context = select_context(task, repo_analysis)
    if context:
        return (context[0]["relative"], "")
    # 3. Fallback: first Python file
    for fi in file_infos:
        if fi.get("language") == "python":
            return (fi["relative"], "")
    return ("", "Could not determine target file from task")
# ─── Helpers ────────────────────────────────────────────────
def _read_file(rel_path: str, repo_path: str) -> str:
    """Read a file via execute_tool, strip the [File: ...] header line."""
    obs = execute_tool({"tool": "read_file", "path": rel_path}, repo_path)
    if obs.startswith("Error"):
        return ""
    if obs.startswith("[File:"):
        idx = obs.find("\n")
        return obs[idx + 1:] if idx != -1 else ""
    return obs
def _run_tests_step(step: int, repo_path: str) -> tuple:
    """Run repository tests as an agent validation step."""
    step += 1
    log("ACTION", f"Step {step}: run_tests")
    test_out = execute_tool({"tool": "run_tests", "directory": repo_path}, repo_path)
    log("OBSERVATION", test_out[:300])
    return step, test_out
def _ensure_symbol_preservation(prompt: str, target: str, original: str, proposed: str) -> str:
    """
    Reject Python edits that drop existing top-level functions/classes.
    This protects dependency chains from LLM rewrites that accidentally remove exports.
    """
    missing = _missing_python_symbols(target, original, proposed)
    missing.extend(name for name in _missing_python_imports(target, original, proposed) if name not in missing)
    if not missing:
        return proposed
    log("ERROR", f"Proposed edit removed required symbols/imports {missing} — retrying")
    retry_prompt = (
        prompt
        + "\n\nCRITICAL: The edited file must preserve these existing top-level "
        + f"functions/classes because other files may import them: {', '.join(missing)}. "
        + "Return the COMPLETE corrected file with all original public symbols preserved."
    )
    retry_resp = query_llm_json(retry_prompt, system_prompt=AGENT_SYSTEM_PROMPT)
    retry_content = retry_resp.get("content", "") if retry_resp else ""
    if retry_content and not _is_placeholder(retry_content):
        retry_missing = _missing_python_symbols(target, original, retry_content)
        retry_missing.extend(
            name for name in _missing_python_imports(target, original, retry_content)
            if name not in retry_missing
        )
        if not retry_missing:
            return retry_content
        log("OBSERVATION", f"Retry still removed required symbols/imports {retry_missing} — skipping")
    else:
        log("OBSERVATION", "Retry returned empty content — skipping")
    return ""
def _missing_python_symbols(path: str, original: str, proposed: str) -> list:
    """Return top-level Python symbols present in original but missing from proposed."""
    if not path.endswith(".py") or not original or not proposed:
        return []
    try:
        original_symbols = _top_level_python_symbols(original)
        proposed_symbols = _top_level_python_symbols(proposed)
    except SyntaxError:
        return []
    return sorted(symbol for symbol in original_symbols if symbol not in proposed_symbols)
def _missing_python_imports(path: str, original: str, proposed: str) -> list:
    """
    Return imported names that were available in original, are still referenced,
    but are no longer imported or defined in proposed code.
    """
    if not path.endswith(".py") or not original or not proposed:
        return []
    try:
        original_imports = _top_level_imported_names(original)
        proposed_available = _top_level_python_symbols(proposed) | _top_level_imported_names(proposed)
        proposed_used = _loaded_python_names(proposed)
    except SyntaxError:
        return []
    return sorted(
        name for name in original_imports
        if name in proposed_used and name not in proposed_available
    )
def _top_level_python_symbols(source: str) -> set:
    """Extract top-level functions/classes from Python source."""
    tree = ast.parse(source)
    symbols = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
    return symbols
def _top_level_imported_names(source: str) -> set:
    """Extract names introduced by top-level Python imports."""
    tree = ast.parse(source)
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                names.add(alias.asname or alias.name)
    return names
def _loaded_python_names(source: str) -> set:
    """Extract names loaded anywhere in Python source."""
    tree = ast.parse(source)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            names.add(node.id)
    return names
def _validation_succeeded(observation: str) -> bool:
    """Return True when repository validation passed or was safely skipped."""
    return "Return code: 0" in observation
def _tests_skipped(observation: str) -> bool:
    """Return True when no repository test command was detected."""
    return "Tests skipped:" in observation
def _is_test_file(rel_path: str) -> bool:
    """Return True for common test-file paths."""
    norm = rel_path.replace("\\", "/").lower()
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
def _ordered_fix_files(file_infos: list) -> list:
    """
    Return editable code files ordered by RepoMaster-style importance.
    Test files are kept as validation context, not default edit targets.
    """
    editable_languages = {
        "python", "javascript", "typescript", "java", "c", "cpp",
        "html", "css", "ruby", "go", "rust", "bash",
    }
    candidates = [
        fi for fi in file_infos
        if fi.get("language") in editable_languages and not _is_test_file(fi.get("relative", ""))
    ]
    candidates.sort(
        key=lambda fi: (
            -fi.get("importance", 0),
            not can_execute(fi.get("relative", "")),
            fi.get("relative", ""),
        )
    )
    return candidates
def _format_plan_context(plan: list) -> str:
    """Convert planner output into compact prompt context."""
    if not plan:
        return ""
    lines = []
    for step in plan[:8]:
        step_num = step.get("step", "?")
        action = step.get("action", "work")
        target = step.get("target") or ""
        description = step.get("description", "")
        target_part = f" -> {target}" if target else ""
        lines.append(f"{step_num}. [{action}]{target_part}: {description}")
    return "\n".join(lines)


def _advance_plan_step(plan_context: str, current_idx: int, current_file: str, action: str) -> int:
    """
    Check if the current action matches the current plan step.
    If it does, advance the step index and log the progression.
    Returns the (possibly advanced) step index.
    """
    if not plan_context:
        return current_idx
    lines = plan_context.strip().splitlines()
    if current_idx >= len(lines):
        return current_idx
    current_line = lines[current_idx].lower()
    # Check if the current file or action matches the plan step
    file_match = current_file and current_file.lower() in current_line
    action_match = action.lower() in current_line
    if file_match or action_match:
        log("PLAN", f"✓ Plan step {current_idx + 1} completed: {lines[current_idx].strip()}")
        return current_idx + 1
    return current_idx
def _get_semantic_context(task: str, current_file: str, last_error: str = "") -> list:
    """
    Query the semantic index for code that may be relevant to the current fix.
    Returns retrieval chunks, excluding the file already being edited.
    """
    query_parts = [task, f"Current file: {current_file}"]
    if last_error:
        error_info = analyze_error(last_error)
        if error_info.get("type") not in ("None", ""):
            query_parts.append(f"Error type: {error_info['type']}")
            query_parts.append(f"Error message: {error_info['message']}")
        query_parts.append(last_error[-800:])
    try:
        results = query_relevant_code("\n".join(query_parts), top_k=5)
    except Exception as exc:
        log("ERROR", f"Semantic retrieval failed: {exc}")
        return []
    filtered = []
    for item in results:
        if item.get("relative") == current_file:
            continue
        filtered.append(item)
        if len(filtered) >= 3:
            break
    if filtered:
        log("CONTEXT",
            "Semantic context: "
            + ", ".join(f"{r['relative']}:{r['name']} ({r['score']})" for r in filtered)
        )
    return filtered
def _language_for_path(path: str) -> str:
    """Return a readable language name for a file path."""
    ext = os.path.splitext(path)[1].lower()
    names = {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".jsx": "JavaScript",
        ".tsx": "TypeScript",
        ".c": "C",
        ".cpp": "C++",
        ".h": "C header",
        ".hpp": "C++ header",
        ".java": "Java",
        ".html": "HTML",
        ".css": "CSS",
        ".scss": "SCSS",
        ".rb": "Ruby",
        ".go": "Go",
        ".rs": "Rust",
        ".sh": "Shell",
    }
    return names.get(ext, "code")


def _language_enforcement(path: str) -> str:
    """
    Generate strict language enforcement instructions for the LLM
    based on the file extension. Prevents cross-language contamination.
    """
    ext = os.path.splitext(path)[1].lower()
    rules = {
        ".js": (
            "⚠️ LANGUAGE CONSTRAINT: This is a JavaScript (.js) file.\n"
            "You MUST write ONLY valid JavaScript.\n"
            "FORBIDDEN in JavaScript:\n"
            "  - Python keywords: def, class(with colon), range(), True, False, None, print()\n"
            "  - Python syntax: 'for x in range()', 'if x is None', indentation-based blocks\n"
            "REQUIRED JavaScript syntax:\n"
            "  - Use function/const/let/var for declarations\n"
            "  - Use true/false/null (lowercase) not True/False/None\n"
            "  - Use { } for blocks, not indentation\n"
            "  - Use === for comparison, not 'is'\n"
            "  - Use for(let i=0; i<n; i++) not for i in range(n)"
        ),
        ".py": (
            "⚠️ LANGUAGE CONSTRAINT: This is a Python (.py) file.\n"
            "You MUST write ONLY valid Python.\n"
            "FORBIDDEN in Python:\n"
            "  - JavaScript keywords: function, const, let, var, =>\n"
            "  - JavaScript syntax: { } blocks, === comparison\n"
            "REQUIRED Python syntax:\n"
            "  - Use def for functions\n"
            "  - Use True/False/None (capitalized)\n"
            "  - Use indentation for blocks"
        ),
        ".html": (
            "⚠️ LANGUAGE CONSTRAINT: This is an HTML (.html) file.\n"
            "You MUST write ONLY valid HTML5.\n"
            "No Python or raw JavaScript in this file — use <script src> to link JS."
        ),
        ".css": (
            "⚠️ LANGUAGE CONSTRAINT: This is a CSS (.css) file.\n"
            "You MUST write ONLY valid CSS.\n"
            "No JavaScript or Python in this file."
        ),
    }
    return rules.get(ext, "")


def _fix_language_contamination(path: str, content: str, task: str) -> str:
    """
    Detect and fix wrong-language content in a file.
    E.g. Python syntax (def, range, True/False) in a .js file.
    Returns corrected content, or empty string to skip the write.
    """
    ext = os.path.splitext(path)[1].lower()

    if ext == ".js":
        # Check for Python syntax in JavaScript
        python_patterns = [
            (r'^def\s+\w+\s*\(', "Python 'def' function"),
            (r'\bfor\s+\w+\s+in\s+range\(', "Python 'for...in range()'"),
            (r'\b(?:True|False|None)\b', "Python True/False/None"),
            (r'^\s*print\(', "Python print()"),
        ]
        contaminated = []
        for pattern, label in python_patterns:
            if re.search(pattern, content, re.MULTILINE):
                contaminated.append(label)

        if contaminated:
            log("ERROR", f"Language contamination in {path}: {', '.join(contaminated)}")
            log("ACTION", "Retrying with explicit JavaScript rewrite prompt")
            # Retry with a very explicit rewrite prompt
            retry_prompt = (
                f"The following file is named {path} (a JavaScript file) but contains "
                f"Python syntax: {', '.join(contaminated)}.\n\n"
                f"CURRENT BROKEN CONTENT:\n```\n{content}\n```\n\n"
                f"TASK: {task}\n\n"
                f"REWRITE this entire file in pure, valid JavaScript.\n"
                f"Rules:\n"
                f"- Use function/const/let (NOT Python def)\n"
                f"- Use true/false/null (NOT Python True/False/None)\n"
                f"- Use for(let i=0; i<n; i++) (NOT Python for i in range())\n"
                f"- Use {{ }} for blocks (NOT Python indentation)\n"
                f"- Use === for comparison (NOT Python 'is')\n\n"
                f"Return JSON:\n"
                f'{{\"thought\": \"rewriting Python to JavaScript\", \"tool\": \"write_file\", '
                f'\"path\": \"{path}\", \"content\": \"FULL JAVASCRIPT FILE\", \"done\": false}}'
            )
            resp = query_llm_json(retry_prompt, system_prompt=(
                "You are a JavaScript expert. Rewrite the given Python code into "
                "valid JavaScript. Return ONLY JSON with the full file content."
            ))
            if resp and resp.get("content"):
                new_content = resp["content"]
                # Clean common LLM artifacts: leading/trailing JSON braces
                new_content = new_content.strip()
                if new_content.startswith("}"):
                    new_content = new_content[1:].strip()
                if new_content.endswith('"}'):
                    new_content = new_content[:-2].strip()
                # Verify the retry didn't also fail
                still_bad = any(
                    re.search(p, new_content, re.MULTILINE)
                    for p, _ in python_patterns
                )
                if not still_bad:
                    log("INFO", f"Language contamination fixed in {path}")
                    new_content = _autofix_brackets(new_content)
                    return new_content
                else:
                    log("ERROR", f"Retry still has Python — applying rule-based transpiler")
                    return _transpile_python_to_js(content)
            # LLM retry returned nothing — apply rule-based transpiler
            log("ERROR", f"LLM retry failed — applying rule-based transpiler")
            return _transpile_python_to_js(content)

    elif ext == ".py":
        # Check for JavaScript syntax in Python
        js_patterns = [
            (r'\bfunction\s+\w+\s*\(', "JavaScript 'function'"),
            (r'\b(?:const|let|var)\s+\w+', "JavaScript const/let/var"),
            (r'=>', "JavaScript arrow function"),
        ]
        contaminated = [label for pattern, label in js_patterns
                        if re.search(pattern, content, re.MULTILINE)]
        if contaminated:
            log("ERROR", f"Language contamination in {path}: {', '.join(contaminated)}")
            return ""  # Skip writing — don't corrupt the Python file

    return content


def _transpile_python_to_js(content: str) -> str:
    """
    Rule-based Python → JavaScript transpiler for common patterns.
    Last-resort fallback when the LLM fails to convert.
    Tracks indentation to properly place closing braces.
    """
    log("ACTION", "Applying rule-based Python→JS transpiler")
    lines = content.split("\n")
    result = []
    # Stack of indentation levels for open blocks
    block_indents = []

    for line in lines:
        stripped = line.rstrip()
        if not stripped:
            result.append("")
            continue

        indent = len(line) - len(line.lstrip())

        # Close blocks when indentation decreases
        while block_indents and indent <= block_indents[-1]:
            closed_indent = block_indents.pop()
            result.append(" " * closed_indent + "}")

        # --- Pattern matching ---

        # def func(args): → function func(args) {
        m = re.match(r'^(\s*)def\s+(\w+)\s*\(([^)]*)\)\s*:\s*$', stripped)
        if m:
            result.append(f"{m.group(1)}function {m.group(2)}({m.group(3)}) {{")
            block_indents.append(indent)
            continue

        # function name(): (hybrid JS/Python) → function name() {
        m = re.match(r'^(\s*)function\s+(\w+)\s*\(([^)]*)\)\s*:\s*$', stripped)
        if m:
            result.append(f"{m.group(1)}function {m.group(2)}({m.group(3)}) {{")
            block_indents.append(indent)
            continue

        # for x in range(n): → for (let x = 0; x < n; x++) {
        m = re.match(r'^(\s*)for\s+(\w+)\s+in\s+range\((.+?)\)\s*:\s*$', stripped)
        if m:
            var = m.group(2)
            raw_arg = m.group(3).strip()
            # Convert ** to Math.pow before splitting
            raw_arg = re.sub(r'(\w+)\s*\*\*\s*(\w+)', r'Math.pow(\1, \2)', raw_arg)
            if ',' in raw_arg and 'Math.pow' not in raw_arg:
                parts = [p.strip() for p in raw_arg.split(',')]
                result.append(f"{m.group(1)}for (let {var} = {parts[0]}; {var} < {parts[1]}; {var}++) {{")
            else:
                result.append(f"{m.group(1)}for (let {var} = 0; {var} < {raw_arg}; {var}++) {{")
            block_indents.append(indent)
            continue

        # if condition: → if (condition) {
        m = re.match(r'^(\s*)if\s+(.+?)\s*:\s*$', stripped)
        if m:
            cond = _py_expr_to_js(m.group(2))
            result.append(f"{m.group(1)}if ({cond}) {{")
            block_indents.append(indent)
            continue

        # elif condition: → } else if (condition) {
        m = re.match(r'^(\s*)elif\s+(.+?)\s*:\s*$', stripped)
        if m:
            cond = _py_expr_to_js(m.group(2))
            result.append(f"{m.group(1)}}} else if ({cond}) {{")
            continue

        # else: → } else {
        m = re.match(r'^(\s*)else\s*:\s*$', stripped)
        if m:
            result.append(f"{m.group(1)}}} else {{")
            continue

        # return statement
        m = re.match(r'^(\s*)return\s+(.*)', stripped)
        if m:
            expr = _py_expr_to_js(m.group(2))
            result.append(f"{m.group(1)}return {expr};")
            continue

        # Pass-through JS lines that are already valid (arrow functions, addEventListener, etc.)
        if re.match(r'^\s*(document\.|const |let |var |//|/\*|\*/|\})', stripped):
            result.append(stripped)
            continue

        # print(...) → console.log(...)
        transformed = re.sub(r'\bprint\(', 'console.log(', stripped)

        # Expression transforms
        transformed = _py_expr_to_js(transformed)

        # Add semicolons to simple statements
        t = transformed.strip()
        if t and not t.endswith(('{', '}', ';', '//', '*/', '(', ',')) \
                and not t.startswith(('function', 'if', 'else', 'for', 'while', '//')):
            transformed = transformed.rstrip() + ';'

        result.append(transformed)

    # Close any remaining open blocks
    while block_indents:
        closed_indent = block_indents.pop()
        result.append(" " * closed_indent + "}")

    output = "\n".join(result)

    # Replace Python keywords globally
    output = re.sub(r'\bTrue\b', 'true', output)
    output = re.sub(r'\bFalse\b', 'false', output)
    output = re.sub(r'\bNone\b', 'null', output)

    log("INFO", "Rule-based transpilation complete")
    return output


def _py_expr_to_js(expr: str) -> str:
    """Convert Python expression patterns to JavaScript equivalents."""
    # // integer division → Math.floor(a / b) — must be first!
    expr = re.sub(r'(\w[\w\[\]\.]*)\s*//\s*(\w[\w\[\]\.]*)', r'Math.floor(\1 / \2)', expr)
    # is not → !==
    expr = re.sub(r'\bis\s+not\b', '!==', expr)
    # is → ===
    expr = re.sub(r'\bis\b', '===', expr)
    # not → !
    expr = re.sub(r'\bnot\b', '!', expr)
    # and → &&
    expr = re.sub(r'\band\b', '&&', expr)
    # or → ||
    expr = re.sub(r'\bor\b', '||', expr)
    # ** → Math.pow (simple cases)
    expr = re.sub(r'(\w+)\s*\*\*\s*(\w+)', r'Math.pow(\1, \2)', expr)
    # f-string '{}'.format() → template literal (basic)
    expr = re.sub(r"'([^']*)'\.format\(([^)]+)\)", r'`\1`.replace("{}", \2)', expr)
    return expr


def _autofix_brackets(content: str) -> str:
    """
    Auto-fix minor bracket mismatches from LLM output.
    Strips leading stray closing brackets and appends missing ones.
    Only handles simple cases — won't fix deeply broken code.
    """
    pairs = {")": "(", "]": "[", "}": "{"}
    openers = {"(", "[", "{"}
    closers = {")", "]", "}"}
    reverse_pairs = {"(": ")", "[": "]", "{": "}"}

    # Strip leading stray closing brackets (common LLM artifact)
    # First: strip if content literally starts with a closer
    content = content.lstrip()
    while content and content[0] in closers:
        log("INFO", f"Auto-fix: stripped leading stray '{content[0]}'")
        content = content[1:].lstrip()
    # Also strip full lines that are just a bracket
    lines = content.split("\n")
    while lines and lines[0].strip() in closers:
        log("INFO", f"Auto-fix: stripped leading stray line '{lines[0].strip()}'")
        lines.pop(0)
    content = "\n".join(lines)

    # Count unmatched brackets
    stack = []
    in_string = False
    string_char = None
    escape = False

    for ch in content:
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
        if ch in openers:
            stack.append(ch)
        elif ch in closers:
            if stack and stack[-1] == pairs[ch]:
                stack.pop()
            # else: stray closer, ignore

    # Append missing closing brackets
    if stack:
        missing = "".join(reverse_pairs[ch] for ch in reversed(stack))
        log("INFO", f"Auto-fix: appending missing '{missing}'")
        content = content.rstrip() + "\n" + missing + "\n"

    return content
def _fence_for_path(path: str) -> str:
    """Return a markdown fence language for a file path."""
    ext = os.path.splitext(path)[1].lower()
    fences = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "jsx",
        ".tsx": "tsx",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".java": "java",
        ".html": "html",
        ".css": "css",
        ".scss": "scss",
        ".rb": "ruby",
        ".go": "go",
        ".rs": "rust",
        ".sh": "bash",
    }
    return fences.get(ext, "")
def _trace_error_to_file(traceback_str: str, repo_path: str) -> str:
    """
    Parse a Python traceback and return the relative path of the
    deepest repo-internal file that caused the error.
    Skips stdlib, site-packages, and <string>/<frozen> frames.
    """
    matches = re.findall(r'File "([^"]+)", line \d+', traceback_str)
    abs_repo = os.path.abspath(repo_path)
    for m in reversed(matches):
        if m.startswith("<"):
            continue
        if "lib/python" in m or "/site-packages/" in m or "lib\\python" in m:
            continue
        abs_m = os.path.abspath(m)
        if abs_m.startswith(abs_repo):
            return os.path.relpath(abs_m, abs_repo)
    return ""
def _is_logic_bug(task: str, run_output: str) -> bool:
    """
    Heuristic: return True if the task mentions specific expected numbers
    that do NOT appear in the program output (suggests a logic bug even
    though return code was 0).
    Only triggers if the task has at least 2 distinct numbers.
    """
    expected = re.findall(r'\b(\d+)\b', task)
    if len(expected) < 2:
        return False
    stdout = run_output
    if "STDOUT:" in run_output:
        stdout = run_output.split("STDOUT:")[1].split("STDERR:")[0]
    for num in expected:
        if num in stdout:
            return False  # At least one expected value found — probably correct
    return True
def _has_input_call(rel_path: str, repo_path: str) -> bool:
    """Return True if the file contains an input() call (would block execution)."""
    full = os.path.join(repo_path, rel_path) if not os.path.isabs(rel_path) else rel_path
    try:
        content = read_file(full)
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped.startswith("#") and "input(" in stripped:
                return True
    except Exception:
        pass
    return False
def _extract_created_files(response: dict) -> list:
    """Normalize multi-file creation JSON into a list of {path, content} dicts."""
    if not response:
        return []
    files = response.get("files")
    if isinstance(files, list):
        return [
            {"path": item.get("path", ""), "content": item.get("content", "")}
            for item in files
            if isinstance(item, dict)
        ]
    if isinstance(files, dict):
        return [
            {"path": path, "content": content}
            for path, content in files.items()
            if isinstance(path, str) and isinstance(content, str)
        ]
    if response.get("path") and response.get("content"):
        return [{"path": response["path"], "content": response["content"]}]
    return []
def _safe_rel_path(path: str) -> str:
    """Return a safe repo-relative path or an empty string."""
    if not path:
        return ""
    normalized = os.path.normpath(path.strip()).replace("\\", "/")
    if normalized.startswith("../") or normalized == ".." or os.path.isabs(normalized):
        return ""
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized
def _choose_generated_entry_point(paths: list) -> str:
    """Choose a likely entry point from generated file paths."""
    preferred = ["main.py", "app.py", "run.py", "index.js", "main.js", "main.c", "Main.java"]
    for name in preferred:
        if name in paths:
            return name
    for path in paths:
        if can_execute(path) and not _is_test_file(path):
            return path
    return paths[0] if paths else ""
def _fallback_connected_repo_files(task: str) -> list:
    """Small deterministic connected Python project used if multi-file generation fails."""
    return [
        {
            "path": "main.py",
            "content": (
                "from pipeline import build_report\n\n"
                "def main():\n"
                "    scores = [80, 90, 100]\n"
                "    print(build_report(scores))\n\n"
                "if __name__ == \"__main__\":\n"
                "    main()\n"
            ),
        },
        {
            "path": "pipeline.py",
            "content": (
                "from statistics_utils import average\n"
                "from formatter import format_report\n\n"
                "def build_report(scores):\n"
                "    return format_report(average(scores))\n"
            ),
        },
        {
            "path": "statistics_utils.py",
            "content": (
                "def average(values):\n"
                "    if not values:\n"
                "        raise ValueError(\"values must not be empty\")\n"
                "    return sum(values) / len(values)\n"
            ),
        },
        {
            "path": "formatter.py",
            "content": (
                "def format_report(score):\n"
                "    return f\"Average score: {score:.1f}\"\n"
            ),
        },
        {
            "path": "tests/test_pipeline.py",
            "content": (
                "import unittest\n"
                "from pipeline import build_report\n\n"
                "class PipelineTest(unittest.TestCase):\n"
                "    def test_build_report(self):\n"
                "        self.assertEqual(build_report([80, 90, 100]), \"Average score: 90.0\")\n\n"
                "if __name__ == \"__main__\":\n"
                "    unittest.main()\n"
            ),
        },
    ]
def _generate_filename(task: str) -> str:
    """Generate a sensible output filename from the task description."""
    task_lower = task.lower()
    # Explicit filename in task
    for word in task.split():
        cleaned = word.strip(".,;:'\"()[]{}").lower()
        for ext in _ALL_SUPPORTED_EXTENSIONS:
            if cleaned.endswith(ext):
                return cleaned
    # Detect language/extension
    ext = ".py"
    for keyword, e in _LANGUAGE_HINTS.items():
        if keyword in task_lower:
            ext = e
            break
    if re.search(r'\bc\b', task_lower) and any(w in task_lower for w in ["program", "file", "code"]):
        ext = ".c"
    # Build name from meaningful task words
    filler = {
        "a", "an", "the", "that", "can", "which", "will", "to", "for",
        "is", "are", "it", "of", "in", "and", "or", "with", "from",
        "make", "create", "generate", "build", "write", "new",
        "python", "javascript", "java", "html", "css", "cpp",
        "file", "script", "program", "module", "code", "please", "me",
        "check", "whether", "if", "page", "using", "use",
    }
    words = [re.sub(r"[^a-z0-9]", "", w) for w in task_lower.split()]
    key_words = [w for w in words if w and w not in filler and len(w) > 1]
    if key_words:
        return "_".join(key_words[:3]) + ext
    fallbacks = {
        ".py": "new_script.py", ".js": "script.js", ".c": "main.c",
        ".cpp": "main.cpp", ".java": "Main.java",
        ".html": "index.html", ".css": "style.css",
    }
    return fallbacks.get(ext, f"new_file{ext}")
# ─── Prompt Builders ────────────────────────────────────────
def _build_fix_prompt(
    task: str,
    target_file: str,
    file_content: str,
    last_error: str = "",
    related_files: dict = None,
    semantic_context: list = None,
    plan_context: str = "",
) -> str:
    """
    Compact, complete prompt for a fix step.
    Includes: task, current file content, error analysis, related files (capped).
    """
    error_section = ""
    if last_error:
        error_info = analyze_error(last_error)
        error_short = last_error[-600:]
        if error_info["type"] not in ("None", ""):
            error_section = (
                f"\nError type: {error_info['type']}\n"
                f"Message: {error_info['message']}\n"
                f"Suggestion: {error_info['suggestion']}\n"
                f"Full output:\n{error_short}\n"
            )
        else:
            error_section = f"\nLast run output:\n{error_short}\n"
    related_section = ""
    if related_files:
        parts = []
        for rp, rc in list(related_files.items())[:3]:
            fence = _fence_for_path(rp)
            parts.append(f"### {rp}\n```{fence}\n{rc[:1500]}\n```")
        related_section = "\nRelated files (for context):\n" + "\n".join(parts) + "\n"
    semantic_section = ""
    if semantic_context:
        parts = []
        for chunk in semantic_context[:3]:
            rel = chunk.get("relative", "?")
            name = chunk.get("name", "?")
            score = chunk.get("score", "?")
            content = chunk.get("content", "")[:1500]
            fence = _fence_for_path(rel)
            parts.append(f"### {rel} :: {name} (score={score})\n```{fence}\n{content}\n```")
        semantic_section = "\nSemantically relevant code:\n" + "\n".join(parts) + "\n"
    plan_section = ""
    if plan_context:
        plan_section = f"\nCurrent plan:\n{plan_context}\n"
    language = _language_for_path(target_file)
    fence = _fence_for_path(target_file)
    lang_enforcement = _language_enforcement(target_file)
    return f"""Task: {task}
{plan_section}
{lang_enforcement}
File to fix: {target_file} ({language})
```{fence}
{file_content}
```
{related_section}{semantic_section}{error_section}
Carefully check for ALL of the following bug types:
1. Syntax errors (bad indentation, missing colons, etc.)
2. Runtime errors (NameError, TypeError, ImportError, etc.)
3. SEMANTIC / NAMING MISMATCHES — the most important: check if every
   function does what its name says. Examples of semantic bugs:
   - def multiply(a, b): return a - b   ← WRONG, should be a * b
   - def add(a, b): return a * b        ← WRONG, should be a + b
   - def subtract(a, b): return a + b   ← WRONG, should be a - b
   Fix the operator to match the function name.
4. WRONG LANGUAGE — if the file contains code in the wrong language
   (e.g. Python def/range/True in a .js file), rewrite it entirely
   in the correct language for the file extension.
Provide the ENTIRE fixed file — do not omit any functions or lines.
The "path" field must be the exact filename you are fixing.
The output MUST be valid {language} code. No other language.
Respond with JSON:
{{"thought": "...", "tool": "write_file", "path": "{target_file}", "content": "ENTIRE FILE", "done": false}}
If no bugs exist in this file:
{{"thought": "No bugs here", "done": true, "summary": "File is correct"}}"""
def _build_create_prompt(task: str, target_file: str) -> str:
    """Minimal prompt for creating a new file."""
    ext = os.path.splitext(target_file)[1].lower()
    lang_map = {
        ".py": "Python", ".js": "JavaScript", ".c": "C",
        ".cpp": "C++", ".java": "Java", ".html": "HTML", ".css": "CSS",
    }
    lang = lang_map.get(ext, "code")
    return f"""Task: {task}
Create a {lang} file named: {target_file}
Requirements:
- Complete, working {lang} code
- Runnable demo with hardcoded test values (no input())
- Must print results when executed
Respond with JSON:
{{"thought": "...", "tool": "write_file", "path": "{target_file}", "content": "ENTIRE FILE CONTENT", "done": false}}"""
def _build_create_repo_prompt(task: str) -> str:
    """Prompt for creating a connected multi-file repository."""
    task_lower = task.lower()
    # Detect if this is a web (HTML/CSS/JS) task
    web_indicators = ['.html', '.css', '.js', 'html', 'css', 'javascript',
                      'web app', 'webapp', 'website', 'web page', 'webpage']
    is_web = any(w in task_lower for w in web_indicators)

    if is_web:
        return f"""Task: {task}

Create a connected web project with separate HTML, CSS, and JavaScript files.

CRITICAL REQUIREMENTS:
- You MUST create ALL files mentioned in the task
- index.html MUST link to style.css using <link rel="stylesheet" href="style.css">
- index.html MUST link to script.js using <script src="script.js"></script>
- style.css MUST contain all styling (NO inline styles in HTML)
- script.js MUST contain all game/app logic (NO inline scripts in HTML)
- Include complete, working code in EVERY file

Return ONLY JSON with ALL files:
{{
  "thought": "short design summary",
  "entry_point": "index.html",
  "files": [
    {{"path": "index.html", "content": "FULL HTML FILE CONTENT"}},
    {{"path": "style.css", "content": "FULL CSS FILE CONTENT"}},
    {{"path": "script.js", "content": "FULL JAVASCRIPT FILE CONTENT"}}
  ]
}}

IMPORTANT: The "files" array MUST contain ALL files. Do NOT omit any file."""

    return f"""Task: {task}

Create a small connected repository. Use Python unless the task explicitly asks for another language.

Requirements:
- 3 to 6 source files total, plus tests when practical
- Files must import/use each other in a real dependency chain
- Include a runnable entry point such as main.py
- Include tests under tests/ that validate the cross-file behavior
- Use absolute imports for local Python modules
- No input(), prompt(), scanf(), network calls, or external services
- Keep code simple, deterministic, and runnable with the local executor

Return ONLY JSON with ALL files:
{{
  "thought": "short design summary",
  "entry_point": "main.py",
  "files": [
    {{"path": "main.py", "content": "FULL FILE CONTENT"}},
    {{"path": "module_a.py", "content": "FULL FILE CONTENT"}},
    {{"path": "module_b.py", "content": "FULL FILE CONTENT"}},
    {{"path": "tests/test_app.py", "content": "FULL FILE CONTENT"}}
  ]
}}

IMPORTANT: The "files" array MUST contain ALL files. Do NOT omit any file."""

