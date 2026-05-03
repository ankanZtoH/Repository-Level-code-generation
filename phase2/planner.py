"""
AI Code Agent — Phase 2: Planner (OpenDevin-style)
Takes a high-level task and breaks it into executable steps.
"""

from utils.logger import log, separator
from utils.llm import query_llm_json


PLANNER_SYSTEM = """You are a software engineering task planner. Given a high-level task description
and optionally a repository map, break the task into concrete, sequential steps.

Each step should be an atomic action like:
- Locate a specific file
- Read a file to understand its content
- Modify a specific function
- Create a new file
- Run code to test
- Run the repository test suite
- Fix an error

Return your plan as JSON."""


def create_plan(task: str, repo_map: str = "") -> list:
    """
    Break a high-level task into sequential steps.

    Returns list of step dicts:
        [{"step": 1, "action": "read|edit|create|run|search", "description": "...", "target": "file.py"}]
    """
    separator("Planning")
    log("PLAN", f"Creating plan for: {task}")

    context = ""
    if repo_map:
        context = f"\n\n## Repository Structure\n{repo_map}"

    # Detect target language from task text
    import re as _re
    lang_hint = ""
    file_mentions = _re.findall(r'\b\w+\.(js|py|html|css|ts|java|c|cpp)\b', task.lower())
    if file_mentions:
        ext_to_lang = {
            "js": "JavaScript", "py": "Python", "html": "HTML", "css": "CSS",
            "ts": "TypeScript", "java": "Java", "c": "C", "cpp": "C++",
        }
        detected = set(ext_to_lang.get(e, e) for e in file_mentions)
        lang_hint = f"\n\nIMPORTANT: Target files use {', '.join(detected)}. " \
                    f"ALL steps must use the correct language. " \
                    f"Do NOT assume Python if the files are {', '.join(detected)}.\n"

    prompt = f"""## Task
{task}
{context}{lang_hint}
## Instructions
Break this task into 3-7 concrete, sequential steps.
Each step must have: step number, action type, description, and target file (if applicable).
Use the CORRECT language for each file (e.g. JavaScript for .js, Python for .py).

Action types: read, edit, create, run, test, search, analyze

Return JSON:
{{
    "plan": [
        {{"step": 1, "action": "read", "description": "Read the file to understand current code", "target": "app.py"}},
        {{"step": 2, "action": "edit", "description": "Fix the bug in add function", "target": "app.py"}},
        {{"step": 3, "action": "run", "description": "Run to verify the fix", "target": "app.py"}}
    ]
}}"""

    result = query_llm_json(prompt, system_prompt=PLANNER_SYSTEM)
    plan = result.get("plan", [])

    if not plan:
        log("ERROR", "Planner returned empty plan, using fallback")
        plan = _fallback_plan(task)

    # Display the plan
    for step in plan:
        step_num = step.get("step", "?")
        action = step.get("action", "?")
        desc = step.get("description", "?")
        target = step.get("target", "")
        target_str = f" → {target}" if target else ""
        log("PLAN", f"Step {step_num} [{action}]{target_str}: {desc}")

    return plan


def _fallback_plan(task: str) -> list:
    """Generate a reasonable fallback plan when LLM fails."""
    task_lower = task.lower()

    if "fix" in task_lower or "bug" in task_lower:
        return [
            {"step": 1, "action": "search", "description": "Search for the relevant code", "target": ""},
            {"step": 2, "action": "read", "description": "Read the file to understand the issue", "target": ""},
            {"step": 3, "action": "edit", "description": "Apply the fix", "target": ""},
            {"step": 4, "action": "run", "description": "Run to verify the fix", "target": ""},
        ]
    elif "create" in task_lower or "generate" in task_lower or "build" in task_lower:
        return [
            {"step": 1, "action": "analyze", "description": "Understand what needs to be created", "target": ""},
            {"step": 2, "action": "create", "description": "Create the main file", "target": ""},
            {"step": 3, "action": "create", "description": "Create supporting files", "target": ""},
            {"step": 4, "action": "run", "description": "Test the created code", "target": ""},
        ]
    else:
        return [
            {"step": 1, "action": "analyze", "description": "Analyze the task requirements", "target": ""},
            {"step": 2, "action": "search", "description": "Find relevant code", "target": ""},
            {"step": 3, "action": "edit", "description": "Make the required changes", "target": ""},
            {"step": 4, "action": "run", "description": "Verify the changes", "target": ""},
        ]
