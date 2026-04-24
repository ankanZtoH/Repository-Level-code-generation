"""
AI Code Agent — Phase 2: Agent Loop (SWE-agent style)
Implements the core THINK → ACT → OBSERVE → REFLECT → REPEAT loop.
Combines concepts from SWE-agent, OpenDevin, OpenHands, and Aider.
"""

import json
import os
from config import MAX_AGENT_STEPS, MAX_RETRIES
from utils.logger import log, separator, banner
from utils.llm import query_llm, query_llm_json
from utils.file_ops import read_file
from phase1.editor import show_diff
from phase2.analyzer import analyze_repo, get_repo_map_text
from phase2.selector import select_context, build_context_prompt
from phase2.planner import create_plan
from phase2.tools import execute_tool, get_tools_description, normalize_tool_name


# ─── System Prompt ──────────────────────────────────────────

AGENT_SYSTEM_PROMPT = """You are an autonomous AI coding agent. You solve tasks by using tools.

CRITICAL RULES:
- To edit a file, use tool "write_file". The "content" field MUST contain the ENTIRE file, not just the changed part.
- After editing, use tool "run_code" to verify.
- Paths are relative to the repo root (e.g. "calculator.py").
- When done, set "done": true.

TOOLS: read_file, write_file, run_code, search_files, create_file, list_directory

You MUST respond with ONLY valid JSON.

Example — read:
{"thought": "Read the file", "tool": "read_file", "path": "calculator.py", "done": false}

Example — write (content MUST be the ENTIRE file):
{"thought": "Fix bug", "tool": "write_file", "path": "calculator.py", "content": "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b\n", "done": false}

Example — run:
{"thought": "Verify fix", "tool": "run_code", "path": "calculator.py", "done": false}

Example — done:
{"thought": "Fix works", "tool": "", "done": true, "summary": "Fixed the add function"}"""


def run_agent(task: str, repo_path: str) -> dict:
    """
    Main agent entry point. Runs the full autonomous pipeline:
    1. Analyze repo
    2. Create plan (OpenDevin-style)
    3. Select context (Aider-style)
    4. Execute SWE-agent loop with tools (OpenHands-style)

    Returns:
        {"success": bool, "summary": str, "steps": int}
    """
    banner("PHASE 2 — AUTONOMOUS AGENT")
    abs_repo = os.path.abspath(repo_path)

    # ── Step 1: Analyze Repository ──
    repo_analysis = analyze_repo(abs_repo)
    repo_map = get_repo_map_text(repo_analysis)

    # ── Step 2: Create Plan (OpenDevin-style) ──
    plan = create_plan(task, repo_map)

    # ── Step 3: Select Context (Aider-style) ──
    context = select_context(task, repo_analysis)
    context_text = build_context_prompt(context) if context else "No files found in repository."

    # ── Step 4: SWE-agent Loop ──
    separator("Agent Loop")
    log("INFO", f"Starting SWE-agent loop (max {MAX_AGENT_STEPS} steps)")

    history = []
    step = 0

    for step in range(1, MAX_AGENT_STEPS + 1):
        separator(f"Step {step}/{MAX_AGENT_STEPS}")

        # Build the prompt with full context
        prompt = _build_step_prompt(
            task=task,
            plan=plan,
            context_text=context_text,
            history=history,
            step=step,
        )

        # THINK + ACT: Get agent's next action
        response = query_llm_json(prompt, system_prompt=AGENT_SYSTEM_PROMPT)

        if not response:
            log("ERROR", "Agent returned empty response, retrying...")
            history.append({
                "step": step,
                "thought": "ERROR: Empty LLM response",
                "action": "none",
                "observation": "Need to retry",
            })
            continue

        # Extract components
        thought = response.get("thought", "No thought provided")
        raw_tool = response.get("tool", "")
        tool_name = normalize_tool_name(raw_tool)
        is_done = response.get("done", False)
        summary = response.get("summary", "")

        # Log THOUGHT
        log("THOUGHT", thought)

        # Check if done
        if is_done:
            log("RESULT", f"Task complete: {summary}")
            return {"success": True, "summary": summary, "steps": step}

        # ACT: Execute the tool
        if tool_name:
            log("ACTION", f"Tool: {tool_name}")

            # Track original content for diff display
            target_file = response.get("path", response.get("file", ""))
            original_content = ""
            if tool_name in ("write_file",) and target_file:
                full_path = os.path.join(abs_repo, target_file) if not os.path.isabs(target_file) else target_file
                if os.path.exists(full_path):
                    original_content = read_file(full_path)

            observation = execute_tool(response, abs_repo)

            # Show diff for file writes (Aider-style)
            if tool_name == "write_file" and original_content:
                new_content = response.get("content", "")
                if new_content and new_content != original_content:
                    show_diff(original_content, new_content, target_file)

            # Log OBSERVATION
            obs_display = observation[:500] if len(observation) > 500 else observation
            log("OBSERVATION", obs_display)

            # Handle errors — feedback loop (only real tool errors, not file content)
            is_tool_error = (
                observation.startswith("Error:") or
                observation.startswith("Error executing") or
                "Return code: 1" in observation or
                "Return code: -1" in observation or
                "Compilation failed" in observation
            )
            if is_tool_error:
                log("FEEDBACK", "Error detected — agent will attempt to fix")
        else:
            observation = "No tool was selected"
            log("OBSERVATION", observation)

        # Record history
        history.append({
            "step": step,
            "thought": thought,
            "action": tool_name or "none",
            "observation": observation[:300],
        })

    # Max steps reached
    log("ERROR", f"Agent reached max steps ({MAX_AGENT_STEPS}) without completing")
    return {
        "success": False,
        "summary": "Max steps reached without task completion",
        "steps": step,
    }


def _build_step_prompt(task, plan, context_text, history, step):
    """Build the full prompt for a single agent step."""
    # Format plan
    plan_text = "\n".join(
        f"  {s.get('step', '?')}. [{s.get('action', '?')}] {s.get('description', '?')}"
        for s in plan
    )

    # Format history
    if history:
        history_lines = []
        for h in history[-5:]:  # Keep last 5 steps for context window
            obs_short = h['observation'][:100].replace('\n', ' ')
            history_lines.append(
                f"  Step {h['step']}: tool={h['action']} | result: {obs_short}"
            )
        history_text = "\n".join(history_lines)
    else:
        history_text = "  No actions taken yet."

    # Determine what to suggest next based on history
    last_actions = [h["action"] for h in history]
    if not history:
        next_hint = "Start by reading the relevant file. Use: {\"tool\": \"read_file\", \"path\": \"filename\"}"
    elif last_actions[-1] == "read_file":
        next_hint = 'Now use write_file to fix the code. IMPORTANT: The "content" field must contain the ENTIRE file with ALL functions — not just the changed line. Copy the whole file from your read_file result and change only the buggy part.'
    elif last_actions[-1] == "write_file":
        next_hint = "Good, you wrote the file. Now use run_code to verify your changes work."
    elif last_actions[-1] == "run_code":
        # Check if last run was successful
        last_obs = history[-1]["observation"]
        if "Return code: 0" in last_obs:
            next_hint = 'The code ran successfully! If the output is correct, set "done": true with a summary.'
        else:
            next_hint = "The code had errors. Use write_file to fix the issues, then run_code again."
    else:
        next_hint = "Decide what to do next."

    return f"""## Task
{task}

## Plan
{plan_text}

## File Contents
{context_text}

## History
{history_text}

## Step {step} — {next_hint}

Respond with ONLY JSON:"""
