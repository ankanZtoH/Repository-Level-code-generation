# """
# AI Code Agent — Phase 2: Agent Loop (Controlled Semi-Autonomous)

# Supports TWO workflows:

# FIX workflow (existing file):
#     Step 1: read_file     (understand code)
#     Step 2: write_file    (fix code)
#     Step 3: run_code      (verify)
#     Step 4: if error -> fix again (max 3 retries)
#     Step 5: if success -> DONE

# CREATE workflow (new file):
#     Step 1: LLM generates code -> write_file
#     Step 2: run_code      (verify)
#     Step 3: if error -> fix (max 3 retries)
#     Step 4: if success -> DONE

# NO free-form tool selection. NO skipping steps.
# """

# import os
# import re
# from config import MAX_AGENT_STEPS, MAX_RETRIES
# from utils.logger import log, separator
# from utils.llm import query_llm, query_llm_json
# from utils.file_ops import read_file
# from phase2.analyzer import analyze_repo, extract_dependency_graph
# from phase2.selector import select_context, build_context_prompt
# from phase2.tools import execute_tool
# from utils.executor import can_execute, NON_EXECUTABLE
# from utils.error_handler import analyze_error


# # ─── Task Classification ────────────────────────────────────

# # Words that indicate creating something new
# _CREATE_KEYWORDS = {
#     "create", "make", "generate", "build", "write", "new",
#     "implement", "add a new", "scaffold", "setup",
# }

# VAGUE_PATTERNS = [
#     "fix all",
#     "fix everything",
#     "fix the code",
#     "fix all code",
#     "improve everything",
#     "refactor all",
#     "clean up everything",
#     "make it better",
#     "update all files",
# ]


# def _is_vague_task(task: str) -> bool:
#     """Reject vague tasks that lack a specific file or bug reference."""
#     task_lower = task.strip().lower()

#     for pattern in VAGUE_PATTERNS:
#         if task_lower == pattern or task_lower.startswith(pattern):
#             return True

#     # Too short to be actionable
#     if len(task_lower.split()) < 3:
#         return True

#     return False


# def _is_create_task(task: str) -> bool:
#     """Detect if the task is about creating a new file rather than fixing one."""
#     task_lower = task.lower()

#     # Check for create keywords at the start of the task
#     for keyword in _CREATE_KEYWORDS:
#         if task_lower.startswith(keyword):
#             return True

#     # Check for "create/make/build ... file" patterns
#     create_patterns = [
#         r"\b(create|make|generate|build|write)\b.*\b(file|script|program|module|page)\b",
#         r"\b(new)\b.*\.(py|js|c|cpp|java|html|css)\b",
#         r"\b(implement|add)\b.*\b(function|class|module)\b.*\b(new|file)\b",
#     ]
#     for pattern in create_patterns:
#         if re.search(pattern, task_lower):
#             return True

#     return False


# # Extension to detect from task keywords
# _LANGUAGE_HINTS = {
#     "python": ".py", "py": ".py",
#     "javascript": ".js", "js": ".js", "node": ".js",
#     "java": ".java",
#     "c++": ".cpp", "cpp": ".cpp",
#     "html": ".html", "webpage": ".html", "web page": ".html",
#     "css": ".css", "stylesheet": ".css", "style": ".css",
# }

# # All supported file extensions
# _ALL_SUPPORTED_EXTENSIONS = {
#     ".py", ".js", ".ts", ".jsx", ".tsx",
#     ".c", ".cpp", ".h", ".hpp",
#     ".java",
#     ".html", ".css", ".scss",
#     ".rb", ".go", ".rs", ".sh",
# }


# def _detect_language_from_task(task: str) -> str:
#     """Detect the target language/extension from the task description."""
#     task_lower = task.lower()

#     # Check for explicit file with extension in the task
#     for word in task.split():
#         cleaned = word.strip(".,;:\"'()[]{}")
#         for ext in _ALL_SUPPORTED_EXTENSIONS:
#             if cleaned.lower().endswith(ext):
#                 return ext

#     # Check for language keywords
#     for keyword, ext in _LANGUAGE_HINTS.items():
#         if keyword in task_lower:
#             return ext

#     # Check for C language (special case — 'c' is too short for generic match)
#     if re.search(r'\bc\b', task_lower) and any(w in task_lower for w in ['program', 'file', 'code', 'function']):
#         return ".c"

#     # Default to Python
#     return ".py"


# def _generate_filename(task: str) -> str:
#     """
#     Generate a sensible filename from a create task description.
#     Detects language from task and uses appropriate extension.
#     e.g. "make a python file that checks even or odd" -> "number_even_odd.py"
#          "create an HTML page" -> "page.html"
#          "write a C program for fibonacci" -> "fibonacci.c"
#     """
#     task_lower = task.lower()

#     # If user explicitly names a file with extension, use it
#     words = task.split()
#     for word in words:
#         cleaned = word.strip(".,;:\"'()[]{}")
#         for ext in _ALL_SUPPORTED_EXTENSIONS:
#             if cleaned.lower().endswith(ext):
#                 return cleaned

#     # Detect language
#     ext = _detect_language_from_task(task)

#     # Extract meaningful words for filename
#     filler = {
#         "a", "an", "the", "that", "can", "which", "will", "to", "for",
#         "is", "are", "it", "of", "in", "and", "or", "with", "from",
#         "make", "create", "generate", "build", "write", "new",
#         "python", "javascript", "java", "html", "css", "cpp",
#         "file", "script", "program", "module", "code", "please", "me",
#         "check", "whether", "wheather", "if", "page", "webpage",
#         "stylesheet", "style", "using", "use",
#     }

#     key_words = []
#     for word in task_lower.split():
#         cleaned = re.sub(r'[^a-z0-9]', '', word)
#         if cleaned and cleaned not in filler and len(cleaned) > 1:
#             key_words.append(cleaned)

#     if key_words:
#         name = "_".join(key_words[:3])
#         return f"{name}{ext}"

#     # Fallback names per language
#     fallback = {
#         ".py": "new_script.py", ".js": "script.js", ".c": "main.c",
#         ".cpp": "main.cpp", ".java": "Main.java", ".html": "index.html",
#         ".css": "style.css",
#     }
#     return fallback.get(ext, f"new_file{ext}")


# # ─── File Extraction (for fix tasks) ────────────────────────

# # Unsupported extensions that should be rejected
# _UNSUPPORTED_EXTENSIONS = {
#     ".swift", ".kt", ".php", ".bat", ".ps1", ".r", ".m", ".sql",
#     ".dart", ".lua", ".pl", ".scala",
# }


# def _extract_target_file(task: str, context: list) -> tuple:
#     """
#     Extract the target file from the task description.

#     Returns:
#         (filename, error_message)
#         - If a supported file is found: ("calculator.py", "")
#         - If an unsupported file is found: ("", "file.swift is not supported...")
#         - If no file found: ("", "")  <-- Proceed to context
#     """
#     words = task.split()
#     for word in words:
#         cleaned = word.strip(".,;:\"'()[]{}")

#         # Check for any supported file extension
#         for ext in _ALL_SUPPORTED_EXTENSIONS:
#             if cleaned.lower().endswith(ext):
#                 return (cleaned, "")

#         # Check for unsupported extensions
#         for ext in _UNSUPPORTED_EXTENSIONS:
#             if cleaned.lower().endswith(ext):
#                 return ("", f"{cleaned} is not supported. Supported: .py, .js, .c, .cpp, .java, .html, .css")

#     # No explicit file mentioned in task — check context
#     if context:
#         return (context[0].get("relative", ""), "")

#     # No file found at all — return empty but NO error yet
#     return ("", "")


# # ─── Loop Protection ────────────────────────────────────────

# class LoopProtector:
#     """Track repeated actions and prevent infinite loops."""

#     def __init__(self, max_repeats: int = 3):
#         self.max_repeats = max_repeats
#         self.action_history = []

#     def record(self, tool: str, target: str, failed: bool):
#         self.action_history.append((tool, target, failed))

#     def is_stuck(self) -> bool:
#         if len(self.action_history) < self.max_repeats:
#             return False
#         recent = self.action_history[-self.max_repeats:]
#         if all(r[0] == recent[0][0] and r[1] == recent[0][1] and r[2] for r in recent):
#             return True
#         return False

#     def suggest_recovery(self) -> str:
#         if not self.action_history:
#             return "search_files"
#         last_tool = self.action_history[-1][0]
#         if last_tool == "write_file":
#             return "read_file"
#         elif last_tool == "run_code":
#             return "read_file"
#         elif last_tool == "read_file":
#             return "search_files"
#         else:
#             return "read_file"


# # ─── Input Detection ────────────────────────────────────────

# def _has_blocking_input(file_path: str, repo_path: str) -> bool:
#     """Check if a Python file contains input() calls that would block execution."""
#     full_path = os.path.join(repo_path, file_path) if not os.path.isabs(file_path) else file_path
#     try:
#         content = read_file(full_path)
#         if not content:
#             return False
#         # Check for input() calls (not inside comments)
#         for line in content.splitlines():
#             stripped = line.strip()
#             if stripped.startswith("#"):
#                 continue
#             if "input(" in stripped:
#                 return True
#         return False
#     except Exception:
#         return False


# def _is_timeout_error(run_result: str) -> bool:
#     """Check if a run result is a timeout error."""
#     return "Timeout after" in run_result or "Return code: -1" in run_result


# # ─── System Prompts ─────────────────────────────────────────

# AGENT_SYSTEM_PROMPT = """You are a coding agent. You fix bugs across multiple files.

# RULES:
# - write_file content MUST be the ENTIRE file, not just the changed part.
# - The "path" field must be the RELATIVE path to the file you are fixing.
# - You may fix a DIFFERENT file than the one shown if the bug is there.
# - NEVER use input() or scanf(). Use hardcoded test values.
# - Do NOT use relative imports (from .module). Use absolute imports.

# Respond with ONLY valid JSON.

# Examples:
# {"thought": "Fix bug in helper", "tool": "write_file", "path": "helper.py", "content": "ENTIRE_FILE", "done": false}
# {"thought": "All bugs fixed", "tool": "", "done": true, "summary": "Fixed multiply and format"}"""

# CREATE_SYSTEM_PROMPT = """You are a coding agent. You create new code files.

# RULES:
# - The "content" field MUST be the COMPLETE, working file.
# - For Python: include if __name__ == "__main__": block.
# - For C/C++: include a main() function with printf output.
# - For Java: include a main method with System.out.println output.
# - For JavaScript: include console.log output at the end.
# - For HTML: write a complete valid HTML5 document.
# - For CSS: write valid CSS with comments.
# - NEVER use input()/scanf()/prompt(). Use hardcoded test values.
# - Write clean, well-documented code.

# Respond with ONLY valid JSON:
# {"thought": "...", "tool": "write_file", "path": "FILENAME.ext", "content": "FULL_FILE_CONTENT", "done": false}"""


# # ─── Entry Point ────────────────────────────────────────────

# def run_agent(task: str, repo_path: str) -> dict:
#     """
#     Run the controlled semi-autonomous agent pipeline.

#     Detects task type:
#       - CREATE task -> generate new file, write, run, verify
#       - FIX task    -> read existing file, fix, run, verify

#     Returns: {"success": bool, "summary": str, "steps": int}
#     """
#     print(f"\n--- AGENT START ---")
#     print(f"Task: {task}")

#     # ── Validate task ──
#     if _is_vague_task(task):
#         print(f"REJECTED: Task is too vague.")
#         print(f"Provide a specific file or bug, e.g.: 'Fix bug in calculator.py'")
#         return {
#             "success": False,
#             "summary": "Task rejected: too vague. Specify a file or specific bug.",
#             "steps": 0,
#         }

#     abs_repo = os.path.abspath(repo_path)

#     # ── Detect task type ──
#     if _is_create_task(task):
#         print("Mode: CREATE")
#         return _execute_create_workflow(task, abs_repo)

#     # ── FIX workflow ──
#     print("Mode: FIX")

#     # Analyze repo
#     repo_analysis = analyze_repo(abs_repo)
#     py_files = repo_analysis.get("files", [])

#     if not py_files:
#         print("ERROR: No Python files found in repository")
#         return {
#             "success": False,
#             "summary": "No Python files found in repository",
#             "steps": 0,
#         }

#     # Build dependency graph
#     dep_graph = extract_dependency_graph(abs_repo, py_files)
#     print(f"Dependency graph: {dep_graph}")

#     # Check for non-Python file references BEFORE context selection
#     target_file, file_error = _extract_target_file(task, [])

#     if file_error:
#         print(f"REJECTED: {file_error}")
#         return {
#             "success": False,
#             "summary": file_error,
#             "steps": 0,
#         }

#     # Select context
#     context = select_context(task, repo_analysis)

#     # If no file was found in the task, try context
#     if not target_file:
#         target_file, file_error = _extract_target_file(task, context)
#         if file_error or not target_file:
#             msg = file_error or "Could not determine target Python file from task."
#             print(f"ERROR: {msg}")
#             return {
#                 "success": False,
#                 "summary": msg,
#                 "steps": 0,
#             }

#     print(f"Entry point: {target_file}")

#     # Execute queue-based fix workflow
#     return _execute_fix_workflow(task, target_file, dep_graph, abs_repo)


# # ─── CREATE Workflow ────────────────────────────────────────

# def _execute_create_workflow(task: str, repo_path: str) -> dict:
#     """
#     Create a new Python file:
#       1. Generate filename from task
#       2. Ask LLM to generate code -> write_file
#       3. run_code to verify
#       4. if error -> fix (max retries)
#       5. if success -> DONE
#     """
#     loop_guard = LoopProtector(max_repeats=MAX_RETRIES)
#     step_count = 0

#     # Step 1: Generate filename
#     target_file = _generate_filename(task)
#     print(f"Target: {target_file}")

#     # Step 2: Ask LLM to generate the file
#     step_count += 1
#     print(f"\nSTEP {step_count}: write_file {target_file}")

#     create_prompt = _build_create_prompt(task, target_file)
#     response = query_llm_json(create_prompt, system_prompt=CREATE_SYSTEM_PROMPT)

#     if not response:
#         print("ERROR: LLM returned empty response")
#         return {"success": False, "summary": "LLM failed to generate code", "steps": step_count}

#     new_content = response.get("content", "")
#     if not new_content:
#         print("ERROR: LLM did not provide file content")
#         return {"success": False, "summary": "LLM did not generate file content", "steps": step_count}

#     # Use the filename from LLM if it provided one (and it's .py)
#     llm_path = response.get("path", "")
#     if llm_path and llm_path.endswith(".py"):
#         target_file = llm_path

#     # Write the file
#     write_action = {"tool": "write_file", "path": target_file, "content": new_content}
#     write_result = execute_tool(write_action, repo_path)

#     if write_result.startswith("Error"):
#         print(f"  {write_result}")
#         return {"success": False, "summary": f"Failed to write {target_file}", "steps": step_count}

#     print(f"  Created {target_file}")

#     # Step 3: Run the code to verify (if executable)
#     if not can_execute(target_file):
#         summary = response.get("thought", f"Created {target_file}")
#         print(f"  Note: {target_file} is not executable (e.g. HTML/CSS). Skipping run step.")
#         print(f"\nDONE: {summary}")
#         return {"success": True, "summary": summary, "steps": step_count}

#     step_count += 1
#     print(f"STEP {step_count}: run_code {target_file}")

#     run_action = {"tool": "run_code", "path": target_file}
#     run_result = execute_tool(run_action, repo_path)

#     print(f"  {run_result[:300]}")

#     if "Return code: 0" in run_result:
#         summary = response.get("thought", f"Created {target_file}")
#         print(f"\nReturn code: 0")
#         print(f"\nDONE: {summary}")
#         return {"success": True, "summary": summary, "steps": step_count}

#     # Handle timeout caused by input() — the file is valid, just interactive
#     if _is_timeout_error(run_result) and _has_blocking_input(target_file, repo_path):
#         print(f"  Note: File uses input() which blocks automated execution.")
#         print(f"  The file was created successfully but requires user input to run.")
#         print(f"\nDONE: Created {target_file} (interactive — uses input())")
#         return {"success": True, "summary": f"Created {target_file} (uses input, runs interactively)", "steps": step_count}

#     # Step 4+: Fix errors in the generated file
#     last_error = run_result
#     loop_guard.record("run_code", target_file, True)

#     for retry in range(1, MAX_RETRIES + 1):
#         if loop_guard.is_stuck():
#             loop_guard = LoopProtector(max_repeats=MAX_RETRIES)

#         # Re-read current file
#         step_count += 1
#         print(f"\nSTEP {step_count}: read_file {target_file}")
#         read_action = {"tool": "read_file", "path": target_file}
#         observation = execute_tool(read_action, repo_path)
#         file_content = observation
#         if observation.startswith("[File:"):
#             newline_idx = observation.find("\n")
#             if newline_idx != -1:
#                 file_content = observation[newline_idx + 1:]

#         # Ask LLM to fix
#         step_count += 1
#         print(f"STEP {step_count}: write_file {target_file}")

#         fix_prompt = _build_fix_prompt(task, target_file, file_content, last_error)
#         response = query_llm_json(fix_prompt, system_prompt=AGENT_SYSTEM_PROMPT)

#         if not response or not response.get("content"):
#             loop_guard.record("write_file", target_file, True)
#             continue

#         new_content = response.get("content", "")
#         write_action = {"tool": "write_file", "path": target_file, "content": new_content}
#         write_result = execute_tool(write_action, repo_path)

#         if write_result.startswith("Error"):
#             loop_guard.record("write_file", target_file, True)
#             continue

#         # Run again
#         step_count += 1
#         print(f"STEP {step_count}: run_code {target_file}")
#         run_action = {"tool": "run_code", "path": target_file}
#         run_result = execute_tool(run_action, repo_path)
#         print(f"  {run_result[:300]}")

#         if "Return code: 0" in run_result:
#             summary = f"Created {target_file}"
#             print(f"\nReturn code: 0")
#             print(f"\nDONE: {summary}")
#             return {"success": True, "summary": summary, "steps": step_count}

#         error_info = analyze_error(run_result)
#         last_error = run_result
#         loop_guard.record("run_code", target_file, True)
#         print(f"  Retry {retry}/{MAX_RETRIES}: {error_info.get('type', 'Error')}")

#     print(f"\nFAILED: Could not create working file after {MAX_RETRIES} retries")
#     return {
#         "success": False,
#         "summary": f"Failed to create working {target_file} after {MAX_RETRIES} retries",
#         "steps": step_count,
#     }


# # ─── FIX Workflow (Queue-Based Multi-File) ──────────────────

# MAX_FILES = 10  # Max files to explore

# def _extract_failing_file(traceback_str: str, repo_path: str) -> str:
#     """Parse traceback to find the deepest repo file that caused the error."""
#     matches = re.findall(r'File "([^"]+)", line \d+', traceback_str)
#     for m in reversed(matches):
#         if m.startswith("<") or "python" in m.lower() or "/lib/" in m.lower():
#             continue
#         abs_m = os.path.abspath(m)
#         if abs_m.startswith(os.path.abspath(repo_path)):
#             return os.path.relpath(abs_m, repo_path)
#     return ""


# def _read_file_content(rel_path: str, repo_path: str) -> str:
#     """Read a file via execute_tool and strip the header."""
#     obs = execute_tool({"tool": "read_file", "path": rel_path}, repo_path)
#     if obs.startswith("Error"):
#         return ""
#     if obs.startswith("[File:"):
#         idx = obs.find("\n")
#         return obs[idx + 1:] if idx != -1 else ""
#     return obs


# def _execute_fix_workflow(task: str, entry_point: str, dep_graph: dict, repo_path: str) -> dict:
#     """
#     Queue-based multi-file fix workflow:
#       1. Run entry_point to get initial error
#       2. Parse traceback -> find failing file
#       3. Read failing file -> ask LLM to fix -> write
#       4. Re-run entry_point to verify
#       5. If new error -> add related files to queue
#       6. Repeat until success or max files explored
#     """
#     step = 0
#     visited = set()
#     queue = [entry_point]
#     files_modified = []
#     last_error = ""

#     # Add dependency graph neighbors to initial queue
#     for dep in dep_graph.get(entry_point, []):
#         if dep not in queue:
#             queue.append(dep)

#     # ── Step 1: Initial run ──
#     if can_execute(entry_point):
#         step += 1
#         print(f"\nSTEP {step}: run_code {entry_point}")
#         run_result = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)
#         last_error = run_result

#         if "Return code: 0" in run_result:
#             print("  Initial run succeeded — checking output for logic bugs...")
#         else:
#             error_info = analyze_error(run_result)
#             print(f"  ERROR: {error_info.get('type', 'Unknown')} — {error_info.get('message', '')[:100]}")

#             # Trace the error to the actual failing file
#             failing = _extract_failing_file(run_result, repo_path)
#             if failing and failing != entry_point and failing not in queue:
#                 print(f"  --> Traced to: {failing}")
#                 queue.insert(0, failing)  # prioritize

#     # ── Step 2: Queue-based exploration ──
#     while queue and len(visited) < MAX_FILES:
#         current_file = queue.pop(0)

#         if current_file in visited:
#             continue
#         visited.add(current_file)

#         print(f"\n{'='*50}")
#         print(f"EXPLORING: {current_file}")
#         print(f"{'='*50}")

#         # Read current file
#         step += 1
#         print(f"\nSTEP {step}: read_file {current_file}")
#         file_content = _read_file_content(current_file, repo_path)

#         if not file_content:
#             print(f"  Cannot read {current_file} — skipping")
#             continue

#         # Build context from related files
#         related_contents = {}
#         for dep in dep_graph.get(current_file, []):
#             dep_content = _read_file_content(dep, repo_path)
#             if dep_content:
#                 related_contents[dep] = dep_content

#         # Ask LLM to fix
#         step += 1
#         print(f"STEP {step}: write_file {current_file}")

#         fix_prompt = _build_fix_prompt(task, current_file, file_content, last_error, related_contents)
#         response = query_llm_json(fix_prompt, system_prompt=AGENT_SYSTEM_PROMPT)

#         if not response:
#             print(f"  LLM returned empty — skipping {current_file}")
#             continue

#         # Check if LLM says done (no fix needed for this file)
#         if response.get("done", False) and not response.get("content"):
#             print(f"  LLM says no fix needed for {current_file}")
#             continue

#         new_content = response.get("content", "")
#         if not new_content:
#             print(f"  No content from LLM — skipping {current_file}")
#             continue

#         # LLM may target a different file
#         target_path = response.get("path", current_file)

#         # Deletion protection
#         if len(file_content) > 100 and len(new_content) < (len(file_content) * 0.6):
#             print(f"  [WARNING] Deletion detected — forcing retry")
#             retry_prompt = f"{fix_prompt}\n\nCRITICAL: Provide the ENTIRE file. Do NOT delete existing code."
#             response = query_llm_json(retry_prompt, system_prompt=AGENT_SYSTEM_PROMPT)
#             new_content = response.get("content", "") if response else ""
#             if not new_content:
#                 continue

#         # Write the fix
#         write_result = execute_tool({"tool": "write_file", "path": target_path, "content": new_content}, repo_path)
#         if "Error" in write_result:
#             print(f"  Write failed: {write_result}")
#             continue

#         files_modified.append(target_path)
#         print(f"  Fixed: {target_path}")

#         # Re-run entry point to verify
#         if can_execute(entry_point):
#             step += 1
#             print(f"\nSTEP {step}: run_code {entry_point} (verify)")
#             run_result = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)
#             last_error = run_result

#             print(f"  {run_result[:300]}")

#             if "Return code: 0" in run_result:
#                 # Check if the LLM is satisfied with the output
#                 print(f"\n  Return code: 0 — checking if output matches task...")

#                 # Quick logic bug check: ask LLM if output is correct
#                 output_lines = run_result.split("Return code: 0")[0].strip()
#                 if output_lines and _output_matches_task(task, output_lines):
#                     summary = f"Fixed {len(files_modified)} file(s): {', '.join(files_modified)}"
#                     print(f"\nDONE: {summary}")
#                     return {"success": True, "summary": summary, "steps": step}
#                 else:
#                     print("  Output may not match expected — continuing exploration...")
#                     # Add remaining deps to check for logic bugs
#                     for dep in dep_graph.get(current_file, []):
#                         if dep not in visited and dep not in queue:
#                             queue.append(dep)
#             else:
#                 # New error — trace it
#                 error_info = analyze_error(run_result)
#                 print(f"  New error: {error_info.get('type', 'Unknown')}")
#                 failing = _extract_failing_file(run_result, repo_path)
#                 if failing and failing not in visited and failing not in queue:
#                     print(f"  --> Traced to: {failing}")
#                     queue.insert(0, failing)

#                 # Also add dependency graph neighbors
#                 for dep in dep_graph.get(current_file, []):
#                     if dep not in visited and dep not in queue:
#                         queue.append(dep)

#     # ── Final result ──
#     if files_modified:
#         summary = f"Modified {len(files_modified)} file(s): {', '.join(files_modified)}"
#         # One final run check
#         if can_execute(entry_point):
#             run_result = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)
#             if "Return code: 0" in run_result:
#                 print(f"\nDONE: {summary}")
#                 return {"success": True, "summary": summary, "steps": step}

#         print(f"\nPARTIAL: {summary} (may still have issues)")
#         return {"success": False, "summary": summary, "steps": step}

#     print(f"\nFAILED: Could not fix any files")
#     return {"success": False, "summary": "Could not fix any files", "steps": step}


# def _output_matches_task(task: str, output: str) -> bool:
#     """Quick heuristic: check if the program output matches numbers/strings mentioned in the task."""
#     # Extract numbers from task description
#     task_numbers = re.findall(r'\b\d+\b', task)
#     if not task_numbers:
#         return True  # No specific numbers to check — trust Return code: 0

#     # Check if the expected result appears in the output
#     # Look for the largest number mentioned (likely the expected result)
#     output_clean = output.replace("STDOUT:", "").replace("STDERR:", "").strip()
#     for num in sorted(task_numbers, key=lambda x: int(x), reverse=True):
#         if num in output_clean:
#             return True

#     return False


# # ─── Prompt Builders (Minimal) ──────────────────────────────

# def _build_fix_prompt(task: str, target_file: str, file_content: str, last_error: str = "", related_files: dict = None) -> str:
#     """
#     Build a minimal prompt for fixing a file.
#     Includes: task, current file, error, and related file contents.
#     """
#     error_section = ""
#     if last_error:
#         error_short = last_error[-500:]
#         error_section = f"\nLast error when running the entry point:\n{error_short}\n"

#     related_section = ""
#     if related_files:
#         parts = []
#         for rel_path, content in related_files.items():
#             parts.append(f"### {rel_path}\n```python\n{content}\n```")
#         related_section = f"\nRelated files (may contain bugs):\n{''.join(parts)}\n"

#     return f"""Task: {task}

# Current file: {target_file}
# ```python
# {file_content}
# ```
# {related_section}{error_section}
# Fix the bug in this file OR in one of the related files.
# The "path" field MUST match the file you are fixing.
# Provide the ENTIRE fixed file content.

# Respond with JSON:
# {{"thought": "...", "tool": "write_file", "path": "FILENAME", "content": "ENTIRE_FILE", "done": false}}

# If this file has no bugs:
# {{"thought": "...", "done": true, "summary": "..."}}"""


# def _build_create_prompt(task: str, target_file: str) -> str:
#     """
#     Build a minimal prompt for creating a new Python file.
#     """
#     return f"""Task: {task}

# Create a Python file named: {target_file}

# Requirements:
# - Write COMPLETE, working Python code
# - Include a if __name__ == "__main__": block that demonstrates the code
# - Do NOT use input(). Use hardcoded test values to demonstrate.
# - The file must run without errors and print results

# Respond with JSON:
# {{"thought": "...", "tool": "write_file", "path": "{target_file}", "content": "ENTIRE_FILE_CONTENT_HERE", "done": false}}"""






















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
from config import MAX_RETRIES
from utils.logger import log, separator
from utils.llm import query_llm_json
from utils.file_ops import read_file
from utils.executor import can_execute
from utils.error_handler import analyze_error
from phase2.analyzer import analyze_repo, extract_dependency_graph
from phase2.selector import select_context
from phase2.tools import execute_tool


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

AGENT_SYSTEM_PROMPT = """You are a coding agent that fixes bugs in Python files.

RULES:
- The "content" field MUST contain the actual Python source code of the fixed file.
- Write the COMPLETE file — every function, every line, nothing omitted.
- "path" must be the exact relative filename (e.g. "calculator.py").
- NEVER use input() or scanf(). Use hardcoded test values only.
- Do NOT use relative imports. Use absolute imports.
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
    and demands actual Python code, no examples.
    Returns the fixed content string, or '' if still unusable.
    """
    retry_prompt = (
        f"Fix all bugs in the file '{file_name}' shown below.\n\n"
        f"```python\n{file_content}\n```\n\n"
        f"Reply ONLY with this JSON (replace content with real Python code):\n"
        f'{{\"thought\": \"...\", \"tool\": \"write_file\", \"path\": \"{file_name}\", '
        f'\"content\": \"<actual python code>\", \"done\": false}}\n\n'
        f"The content field must contain real, runnable Python source code."
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
    print(f"\n--- AGENT START ---")
    print(f"Task: {task}")

    abs_repo = os.path.abspath(repo_path)

    if _is_create_task(task):
        print("Mode: CREATE")
        return _run_create(task, abs_repo)

    print("Mode: FIX")
    return _run_fix(task, abs_repo)


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
    dep_graph = extract_dependency_graph(repo_path, file_infos)
    print(f"Dependency graph: {dep_graph}")

    # Broad task: fix all files
    if _is_broad_task(task):
        print("Broad task — exploring all Python files")
        return _run_fix_all(task, file_infos, dep_graph, repo_path)

    # Targeted task: find the specific entry point
    entry_point, err = _find_entry_point(task, repo_path, file_infos, repo_analysis)
    if err:
        return {"success": False, "summary": err, "steps": 0}

    print(f"Entry point: {entry_point}")
    return _run_fix_targeted(task, entry_point, dep_graph, repo_path)


def _run_fix_targeted(task: str, entry_point: str, dep_graph: dict, repo_path: str) -> dict:
    """
    Fix a specific entry point and its dependencies using queue traversal.
    """
    step = 0
    visited = set()
    files_modified = []
    last_run_output = ""

    # Seed queue: entry point first, then its direct deps
    queue = [entry_point]
    for dep in dep_graph.get(entry_point, []):
        if dep not in queue:
            queue.append(dep)

    # Initial run to get baseline error
    if can_execute(entry_point):
        step += 1
        print(f"\nSTEP {step}: run_code {entry_point}")
        run_out = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)
        last_run_output = run_out
        print(f"  {run_out[:300]}")

        if "Return code: 0" in run_out:
            if not _is_logic_bug(task, run_out):
                return {
                    "success": True,
                    "summary": f"No fix needed — {entry_point} already runs correctly",
                    "steps": step,
                }
            print("  Return code 0 but output looks wrong — checking for logic bugs")
        else:
            error_info = analyze_error(run_out)
            print(f"  ERROR: {error_info['type']} — {error_info['message'][:100]}")
            # Trace to actual failing file and prioritize it
            failing = _trace_error_to_file(run_out, repo_path)
            if failing and failing != entry_point and failing not in queue:
                print(f"  Traced to: {failing}")
                queue.insert(0, failing)

    # Queue-based exploration
    while queue and len(visited) < MAX_FILES:
        current = queue.pop(0)

        if current in visited:
            continue
        visited.add(current)

        print(f"\n{'='*50}")
        print(f"EXPLORING: {current}  (visited {len(visited)}/{MAX_FILES})")
        print(f"{'='*50}")

        # Read the file
        step += 1
        print(f"\nSTEP {step}: read_file {current}")
        file_content = _read_file(current, repo_path)

        if not file_content:
            print(f"  Cannot read {current} — skipping")
            continue

        # Build related file context
        related = {}
        for dep in dep_graph.get(current, []):
            c = _read_file(dep, repo_path)
            if c:
                related[dep] = c

        # Ask LLM to fix
        step += 1
        print(f"STEP {step}: LLM fix {current}")
        prompt = _build_fix_prompt(task, current, file_content, last_run_output, related)
        response = query_llm_json(prompt, system_prompt=AGENT_SYSTEM_PROMPT)

        if not response:
            print(f"  LLM returned empty — skipping {current}")
            continue

        # LLM says no bug here
        if response.get("done") and not response.get("content"):
            print(f"  LLM: no bug in {current}")
            for dep in dep_graph.get(current, []):
                if dep not in visited and dep not in queue:
                    queue.append(dep)
            continue

        new_content = response.get("content", "")
        if not new_content:
            print(f"  No content from LLM — skipping {current}")
            continue

        # Placeholder guard
        if _is_placeholder(new_content):
            print(f"  [WARN] LLM returned a placeholder — retrying")
            new_content = _retry_for_real_content(current, file_content)
            if not new_content:
                print(f"  Retry placeholder — skipping {current}")
                continue

        # LLM may target a different file
        target = response.get("path", current) or current

        # Deletion protection (only for large files)
        orig_content = file_content if target == current else (_read_file(target, repo_path) or "")
        if orig_content and len(orig_content) > 500 and len(new_content) < len(orig_content) * 0.5:
            print(f"  [WARN] Output too short ({len(new_content)} vs {len(orig_content)}) — skipping")
            continue


        # Write the fix
        step += 1
        print(f"STEP {step}: write_file {target}")
        write_out = execute_tool({"tool": "write_file", "path": target, "content": new_content}, repo_path)

        if write_out.startswith("Error"):
            print(f"  Write failed: {write_out}")
            continue

        if target not in files_modified:
            files_modified.append(target)
        print(f"  Written: {target}")

        # Non-runnable file — skip verification, treat write as success
        if not can_execute(entry_point):
            summary = f"Fixed {', '.join(files_modified)}"
            print(f"\nDONE: {summary}")
            return {"success": True, "summary": summary, "steps": step}

        # Re-run entry point to verify
        step += 1
        print(f"\nSTEP {step}: run_code {entry_point} (verify)")
        run_out = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)
        last_run_output = run_out
        print(f"  {run_out[:300]}")

        if "Return code: 0" in run_out:
            if not _is_logic_bug(task, run_out):
                summary = f"Fixed {', '.join(files_modified)}"
                print(f"\nDONE: {summary}")
                return {"success": True, "summary": summary, "steps": step}
            print("  Output still looks wrong — continuing exploration")
            for dep in dep_graph.get(current, []):
                if dep not in visited and dep not in queue:
                    queue.append(dep)
        else:
            # Still failing — trace new error and expand queue
            error_info = analyze_error(run_out)
            print(f"  Still failing: {error_info['type']} — {error_info['message'][:80]}")
            failing = _trace_error_to_file(run_out, repo_path)
            if failing and failing not in visited and failing not in queue:
                print(f"  Traced to: {failing}")
                queue.insert(0, failing)
            for dep in dep_graph.get(current, []):
                if dep not in visited and dep not in queue:
                    queue.append(dep)

    # Final result
    if files_modified:
        if can_execute(entry_point):
            run_out = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)
            if "Return code: 0" in run_out and not _is_logic_bug(task, run_out):
                summary = f"Fixed {', '.join(files_modified)}"
                print(f"\nDONE: {summary}")
                return {"success": True, "summary": summary, "steps": step}
        summary = f"Modified {', '.join(files_modified)} — may still have issues"
        print(f"\nPARTIAL: {summary}")
        return {"success": False, "summary": summary, "steps": step}

    print("\nFAILED: No files could be fixed")
    return {"success": False, "summary": "Could not fix any files", "steps": step}


def _run_fix_all(task: str, file_infos: list, dep_graph: dict, repo_path: str) -> dict:
    """
    Broad fix-all mode: EXECUTION-DRIVEN, GRAPH-AWARE debug loop.

    Algorithm:
      1. Find the project entry point (main.py, app.py, or first runnable .py).
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
    py_files = [f for f in file_infos if f.get("language") == "python"]
    if not py_files:
        return {"success": False, "summary": "No Python files found", "steps": 0}

    ENTRY_NAMES = ["main.py", "app.py", "run.py", "start.py", "__main__.py"]
    entry_point = ""
    for name in ENTRY_NAMES:
        for fi in py_files:
            if os.path.basename(fi["relative"]) == name:
                entry_point = fi["relative"]
                break
        if entry_point:
            break
    if not entry_point:
        entry_point = py_files[0]["relative"]

    print(f"Entry point: {entry_point}")

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
    # Add any remaining py files not reachable from entry
    for fi in py_files:
        if fi["relative"] not in seen_for_seed:
            queue.append(fi["relative"])

    # ── 3. Initial run ───────────────────────────────────────
    step += 1
    print(f"\nSTEP {step}: run_code {entry_point}")
    run_out = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)
    last_run_output = run_out
    print(f"  {run_out[:300]}")

    # Even if it runs clean, we still scan all files for logic/semantic bugs
    system_runs_clean = "Return code: 0" in run_out

    if "Return code: 0" not in run_out:
        error_info = analyze_error(run_out)
        print(f"  ERROR: {error_info['type']} — {error_info['message'][:100]}")
        failing = _trace_error_to_file(run_out, repo_path)
        if failing:
            print(f"  Traced to: {failing}")
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

        print(f"\n{'='*50}")
        print(f"EXPLORING: {current}  [{iteration}/{MAX_ITERATIONS}]")
        print(f"{'='*50}")

        # 4a. Read
        step += 1
        print(f"\nSTEP {step}: read_file {current}")
        file_content = _read_file(current, repo_path)
        if not file_content:
            print(f"  Cannot read {current} — skipping")
            continue

        related = {}
        for dep in dep_graph.get(current, []):
            c = _read_file(dep, repo_path)
            if c:
                related[dep] = c

        # 4b. LLM fix
        step += 1
        print(f"STEP {step}: LLM fix {current}")
        prompt = _build_fix_prompt(task, current, file_content, last_run_output, related)
        response = query_llm_json(prompt, system_prompt=AGENT_SYSTEM_PROMPT)

        if not response:
            print(f"  LLM returned empty — skipping {current}")
            continue

        if response.get("done") and not response.get("content"):
            print(f"  LLM: no bug in {current} — expanding deps")
            for dep in dep_graph.get(current, []):
                if dep not in visited and dep not in queue:
                    queue.append(dep)
            continue

        new_content = response.get("content", "")
        if not new_content:
            print(f"  No content from LLM — skipping {current}")
            continue

        # Placeholder guard: reject if LLM echoed example text
        if _is_placeholder(new_content):
            print(f"  [WARN] LLM returned a placeholder — retrying with direct instruction")
            new_content = _retry_for_real_content(current, file_content)
            if not new_content:
                print(f"  Retry returned empty or placeholder — skipping {current}")
                continue

        target = response.get("path", current) or current

        # Deletion protection: only block truly massive regressions on large files
        orig_content = file_content if target == current else (_read_file(target, repo_path) or "")
        if orig_content and len(orig_content) > 500 and len(new_content) < len(orig_content) * 0.5:
            print(f"  [WARN] Fix too short ({len(new_content)} vs {len(orig_content)}) — retrying")
            retry_prompt = prompt + "\n\nCRITICAL: Provide the ENTIRE fixed file — do NOT omit any functions or lines."
            retry_resp = query_llm_json(retry_prompt, system_prompt=AGENT_SYSTEM_PROMPT)
            if retry_resp and retry_resp.get("content") and not _is_placeholder(retry_resp["content"]):
                new_content = retry_resp["content"]
                target = retry_resp.get("path", target) or target
            else:
                print(f"  Retry also empty — skipping")
                continue


        # 4c. Write
        step += 1
        print(f"STEP {step}: write_file {target}")
        write_out = execute_tool({"tool": "write_file", "path": target, "content": new_content}, repo_path)
        if write_out.startswith("Error"):
            print(f"  Write failed: {write_out}")
            continue

        if target not in files_modified:
            files_modified.append(target)
        print(f"  Written: {target}")

        # 4d. Re-run entry point — validate the WHOLE system
        step += 1
        print(f"\nSTEP {step}: run_code {entry_point}  <- system validation")
        run_out = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)
        last_run_output = run_out
        print(f"  {run_out[:300]}")

        if "Return code: 0" in run_out:
            system_runs_clean = True
            print("  Return code: 0 — continuing to check remaining files for logic/semantic bugs")
            # Don't stop here — keep exploring the rest of the queue
            # so we catch naming mismatches (e.g. multiply() doing division)
            for dep in dep_graph.get(current, []):
                if dep not in visited and dep not in queue:
                    queue.append(dep)
        else:
            # 4e. Trace new error
            error_info = analyze_error(run_out)
            print(f"  Still failing: {error_info['type']} — {error_info['message'][:80]}")
            failing = _trace_error_to_file(run_out, repo_path)
            if failing and failing not in visited:
                print(f"  Traced to: {failing}")
                if failing in queue:
                    queue.remove(failing)
                queue.insert(0, failing)
            for dep in dep_graph.get(current, []):
                if dep not in visited and dep not in queue:
                    queue.append(dep)

    # ── 5. Final validation ───────────────────────────────────
    step += 1
    print(f"\nSTEP {step}: run_code {entry_point}  <- final validation")
    final_out = execute_tool({"tool": "run_code", "path": entry_point}, repo_path)
    print(f"  {final_out[:300]}")

    if "Return code: 0" in final_out:
        if files_modified:
            summary = f"Fixed {', '.join(files_modified)}"
        else:
            summary = "All files inspected — no bugs found"
        print(f"\nDONE: {summary}")
        return {"success": True, "summary": summary, "steps": step}

    if files_modified:
        summary = f"Modified {', '.join(files_modified)} — may still have residual issues"
        print(f"\nPARTIAL: {summary}")
        return {"success": False, "summary": summary, "steps": step}

    print("\nFAILED: No files could be fixed")
    return {"success": False, "summary": "Could not fix any files", "steps": step}


# ─── CREATE Mode ────────────────────────────────────────────

def _run_create(task: str, repo_path: str) -> dict:
    """
    Create a new file from scratch, run it, fix errors up to MAX_RETRIES.
    """
    step = 0
    target = _generate_filename(task)
    print(f"Target: {target}")

    # Generate
    step += 1
    print(f"\nSTEP {step}: generate {target}")
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
    print(f"STEP {step}: write_file {target}")
    write_out = execute_tool({"tool": "write_file", "path": target, "content": content}, repo_path)
    if write_out.startswith("Error"):
        return {"success": False, "summary": f"Write failed: {write_out}", "steps": step}
    print(f"  Created {target}")

    # Non-executable — done immediately
    if not can_execute(target):
        print(f"  {target} is not executable — done")
        return {"success": True, "summary": f"Created {target}", "steps": step}

    # Run
    step += 1
    print(f"STEP {step}: run_code {target}")
    run_out = execute_tool({"tool": "run_code", "path": target}, repo_path)
    print(f"  {run_out[:300]}")

    if "Return code: 0" in run_out:
        return {"success": True, "summary": f"Created {target}", "steps": step}

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
        print(f"\n  Retry {retry}/{MAX_RETRIES}")

        step += 1
        print(f"STEP {step}: read_file {target}")
        current_content = _read_file(target, repo_path)
        if not current_content:
            break

        step += 1
        print(f"STEP {step}: LLM fix {target}")
        fix_prompt = _build_fix_prompt(task, target, current_content, last_error)
        response = query_llm_json(fix_prompt, system_prompt=AGENT_SYSTEM_PROMPT)

        if not response or not response.get("content"):
            continue

        new_content = response["content"]
        execute_tool({"tool": "write_file", "path": target, "content": new_content}, repo_path)

        step += 1
        print(f"STEP {step}: run_code {target}")
        run_out = execute_tool({"tool": "run_code", "path": target}, repo_path)
        print(f"  {run_out[:300]}")
        last_error = run_out

        if "Return code: 0" in run_out:
            return {"success": True, "summary": f"Created {target}", "steps": step}

        error_info = analyze_error(run_out)
        print(f"  Error: {error_info['type']} — {error_info['suggestion'][:80]}")

    return {
        "success": False,
        "summary": f"Created {target} but could not fix errors after {MAX_RETRIES} retries",
        "steps": step,
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
            parts.append(f"### {rp}\n```python\n{rc[:1500]}\n```")
        related_section = "\nRelated files (for context):\n" + "\n".join(parts) + "\n"

    return f"""Task: {task}

File to fix: {target_file}
```python
{file_content}
```
{related_section}{error_section}
Carefully check for ALL of the following bug types:
1. Syntax errors (bad indentation, missing colons, etc.)
2. Runtime errors (NameError, TypeError, ImportError, etc.)
3. SEMANTIC / NAMING MISMATCHES — the most important: check if every
   function does what its name says. Examples of semantic bugs:
   - def multiply(a, b): return a - b   ← WRONG, should be a * b
   - def add(a, b): return a * b        ← WRONG, should be a + b
   - def subtract(a, b): return a + b   ← WRONG, should be a - b
   Fix the operator to match the function name.
4. Logic errors (wrong formula, wrong condition, etc.)

Provide the ENTIRE fixed file — do not omit any functions or lines.
The "path" field must be the exact filename you are fixing.

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