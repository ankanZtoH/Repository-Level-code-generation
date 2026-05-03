"""
AI Code Agent — SWE-Agent Conversational Loop (Upgraded)
========================================================

Implements the strict SWE-agent pipeline:
  PLAN → RETRIEVE → THINK → ACT → OBSERVE → FIX → REPEAT

Key upgrades:
  - Strict pipeline enforcement (FIX 1)
  - Authoritative planner with step validation (FIX 2)
  - Mandatory retrieval before edit actions (FIX 3)
  - Repo graph integrated into context (FIX 4)
  - Minimum 3 retries per error (FIX 5)
  - Structured error → fix mapping (FIX 6)
  - Agent mode switching (FIX 7)
  - Attempt memory to prevent repeated mistakes (FIX 8)
  - Unified control loop (FIX 9)
"""

import os
import json
from utils.logger import log, separator
from utils.llm import query_llm_chat
from utils.file_ops import read_file
from utils.error_handler import analyze_error
from utils.validator import validate_syntax
from phase2.tools import execute_tool, get_tools_prompt, normalize_tool_name
from phase2.analyzer import (analyze_repo, extract_dependency_graph, get_repo_map_text,
                              build_semantic_graph, print_dependency_graph,
                              get_reverse_deps, format_graph_compact)
from phase2.planner import create_plan
from phase2.retrieval import index_repo, query_relevant_code
from phase2.agent import LoopProtector, AgentMode, MODE_SYSTEM_HINTS

# Maximum characters per observation to prevent context overflow
MAX_OBSERVATION_CHARS = 3000
MIN_RETRIES_PER_ERROR = 3


class SWEAgentLoop:
    """
    SWE-agent style conversational loop with strict pipeline enforcement.
    Integrates: planner, retrieval, repo graph, error handler, agent modes.
    """

    def __init__(self, repo_path: str, max_steps: int = 15):
        self.repo_path = os.path.abspath(repo_path)
        self.max_steps = max_steps
        self.messages = []
        self.protector = LoopProtector(max_steps=max_steps)
        self.files_modified = []
        self.step_count = 0

        # FIX 7: Agent mode tracking
        self.mode = AgentMode.PLANNING

        # FIX 8: Attempt memory — prevents repeating mistakes
        self.attempt_history = []

        # FIX 2: Plan tracking
        self.plan = []
        self.current_plan_step = 0

        # FIX 4: Repo analysis + dependency graph
        self.repo_analysis = None
        self.dep_graph = {}

        # FIX 5: Error retry tracking
        self.consecutive_errors = 0

    def run(self, task: str) -> dict:
        """
        Run the SWE-agent loop with strict pipeline.
        Pipeline: PLAN → RETRIEVE → THINK → ACT → OBSERVE → FIX → REPEAT
        Returns: {"success": bool, "summary": str, "steps": int}
        """
        separator("SWE-AGENT START")
        log("PLAN", f"Task: {task}")

        # ── Phase 1: PLAN (FIX 1, FIX 2) ──
        self.mode = AgentMode.PLANNING
        log("THOUGHT", f"Entering {self.mode.value.upper()} mode")

        # Analyze repo + build semantic dependency graph (FIX 4)
        self.repo_analysis = analyze_repo(self.repo_path)
        import_graph = self.repo_analysis.get("dependency_graph") or \
            extract_dependency_graph(self.repo_path, self.repo_analysis.get("files", []))
        # Upgrade to semantic graph (import + call-level edges)
        self.dep_graph = build_semantic_graph(
            self.repo_analysis.get("files", []), import_graph
        )
        log("INFO", f"Semantic dependency graph: {len(self.dep_graph)} files mapped")
        # Terminal visualization (FIX POINT 3)
        print_dependency_graph(self.dep_graph)

        # Build semantic index for retrieval (FIX 3)
        n_indexed = index_repo(self.repo_analysis)
        if n_indexed:
            log("INFO", f"Semantic index: {n_indexed} chunks indexed")

        # Generate authoritative plan (FIX 2)
        repo_map = get_repo_map_text(self.repo_analysis)
        self.plan = create_plan(task, repo_map)
        if not self.plan:
            log("ERROR", "Planner returned empty plan — using direct mode")

        # ── Phase 2: Build system prompt + context ──
        system_prompt = self._build_system_prompt(task)
        user_message = self._build_task_message(task)

        self.messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # ── Phase 3: EXECUTE loop (FIX 1, FIX 5) ──
        self.mode = AgentMode.EXECUTING
        log("THOUGHT", f"Switching to {self.mode.value.upper()} mode")

        result = {"success": False, "summary": "Agent did not complete", "steps": 0}

        while self.step_count < self.max_steps:
            step_result = self._step(task)

            if step_result == "done":
                result["success"] = True
                result["summary"] = (
                    f"Completed in {self.step_count} steps. "
                    f"Modified: {', '.join(self.files_modified) or 'none'}"
                )
                break
            elif step_result == "error":
                self.consecutive_errors += 1
                # FIX 5: Don't stop until minimum retries exhausted
                if self.consecutive_errors >= MIN_RETRIES_PER_ERROR:
                    log("ERROR", f"Failed after {MIN_RETRIES_PER_ERROR} consecutive retries")
                    # Switch to debugging mode for deeper analysis
                    if self.mode != AgentMode.DEBUGGING:
                        self.mode = AgentMode.DEBUGGING
                        log("THOUGHT", f"Switching to {self.mode.value.upper()} mode")
                        self._inject_mode_hint()
                    self.consecutive_errors = 0  # reset to allow more attempts
            elif step_result == "stop":
                result["summary"] = (
                    f"Stopped after {self.step_count} steps: "
                    f"{self.protector.should_stop()[1]}"
                )
                break
            else:
                # Success — reset error counter
                self.consecutive_errors = 0

        result["steps"] = self.step_count
        log("RESULT" if result["success"] else "ERROR", result["summary"])
        return result

    def _step(self, task: str) -> str:
        """
        Execute one step of the strict pipeline:
          RETRIEVE → THINK → ACT → OBSERVE → (FIX if error)
        Returns: "done", "continue", "error", or "stop"
        """
        self.step_count += 1

        # Check limits
        stop, reason = self.protector.should_stop()
        if stop:
            log("ERROR", f"Loop halted: {reason}")
            return "stop"

        separator(f"Step {self.step_count}")

        # ── FIX 2: Inject current plan step into context ──
        self._inject_plan_step()

        # 1. Query LLM with full history
        raw_response = query_llm_chat(self.messages, expect_json=True)

        if not raw_response:
            log("ERROR", "LLM returned empty response")
            self._add_observation("Error: LLM returned empty response. Please try again.")
            self.protector.record("query", "llm", False)
            return "error"

        # 2. Parse response
        try:
            response = json.loads(raw_response)
        except json.JSONDecodeError:
            log("ERROR", f"Invalid JSON from LLM: {raw_response[:200]}")
            self._add_observation(
                "Error: Your response was not valid JSON. "
                "Please respond with a JSON object containing 'thought' and 'action'."
            )
            self.protector.record("query", "llm", False)
            return "error"

        # Add assistant message to history
        self.messages.append({"role": "assistant", "content": raw_response})

        # Extract thought
        thought = response.get("thought", "")
        if thought:
            log("THOUGHT", thought[:200])

        # Extract action
        action = response.get("action", {})
        if not action:
            self._add_observation(
                "Error: No 'action' field in your response. "
                "Include an action like {\"tool\": \"read_file\", \"path\": \"file.py\"}"
            )
            self.protector.record("query", "llm", False)
            return "error"

        tool_name = normalize_tool_name(action.get("tool", ""))

        # 3. Check if done
        if tool_name == "done" or action.get("tool", "").lower() == "done":
            summary = response.get("summary", thought or "Task completed")
            log("RESULT", f"Agent signals done: {summary}")
            return "done"

        # ── FIX 3: Mandatory retrieval before edit actions ──
        if tool_name in ("write_file", "patch_file", "create_file"):
            target_path = action.get("path", "")
            self._retrieve_context(target_path, task)

        # 4. Execute the action
        log("ACTION", f"Step {self.step_count}: {tool_name} {action.get('path', '')}")

        try:
            observation = execute_tool(action, self.repo_path)
        except Exception as e:
            observation = f"Error executing {tool_name}: {e}"
            log("ERROR", observation)

        # Track modifications
        if tool_name in ("write_file", "patch_file", "create_file"):
            path = action.get("path", "")
            if path and path not in self.files_modified:
                self.files_modified.append(path)

        # Record in protector
        success = "Error" not in observation[:20]
        self.protector.record(tool_name, action.get("path", ""), success)

        # ── FIX 8: Record attempt in history ──
        self.attempt_history.append({
            "step": self.step_count,
            "tool": tool_name,
            "path": action.get("path", ""),
            "success": success,
            "result_preview": observation[:150],
        })

        # ── FIX 6: Structured error → fix mapping ──
        if not success and observation.startswith("Error"):
            error_info = analyze_error(observation, action.get("path", ""))
            self._inject_error_feedback(error_info, observation)
            # FIX 7: Switch to debugging mode
            if self.mode != AgentMode.DEBUGGING:
                self.mode = AgentMode.DEBUGGING
                log("THOUGHT", f"Switching to {self.mode.value.upper()} mode")
            return "error"

        # ── FIX 2: Advance plan step on success ──
        if success and self.plan and self.current_plan_step < len(self.plan):
            step_info = self.plan[self.current_plan_step]
            step_action = step_info.get("action", "")
            # Advance if action type matches
            if self._action_matches_plan(tool_name, step_action):
                self.current_plan_step += 1
                log("PLAN", f"✓ Plan step {self.current_plan_step} completed")
                # Switch back to executing mode after successful debug
                if self.mode == AgentMode.DEBUGGING:
                    self.mode = AgentMode.EXECUTING
                    log("THOUGHT", f"Switching back to {self.mode.value.upper()} mode")

        # 5. Add observation to history (truncated)
        truncated = self._truncate(observation)
        log("OBSERVATION", truncated[:300])
        self._add_observation(truncated)

        return "continue"

    # ─── Pipeline Helpers ───────────────────────────────────

    def _retrieve_context(self, target_path: str, task: str):
        """FIX 3: Mandatory retrieval before any edit action."""
        query = f"{task} {target_path}"
        results = query_relevant_code(query, top_k=3)
        if results:
            context_parts = []
            for r in results:
                rel = r.get("relative", r.get("name", ""))
                score = r.get("score", 0)
                context_parts.append(f"  - {rel} (relevance: {score:.3f})")
            log("CONTEXT", f"Retrieved {len(results)} relevant chunks for {target_path}")

            # FIX 4: Add dependency neighbors (imports)
            dep_neighbors = self.dep_graph.get(target_path, [])
            if dep_neighbors:
                context_parts.append(f"\nDependencies of {target_path} (imports):")
                for dep in dep_neighbors[:5]:
                    context_parts.append(f"  - {dep}")
                log("CONTEXT", f"Added {len(dep_neighbors)} dependency neighbors")

            # FIX 4: Add reverse dependencies (who imports this file)
            reverse_deps = get_reverse_deps(self.dep_graph, target_path)
            if reverse_deps:
                context_parts.append(f"\nDepended on by (reverse deps):")
                for rdep in reverse_deps[:5]:
                    context_parts.append(f"  - {rdep}")
                log("CONTEXT", f"Added {len(reverse_deps)} reverse dependencies")

            context_msg = (
                f"CONTEXT for editing {target_path}:\n"
                f"Related files:\n" + "\n".join(context_parts)
            )
            self._add_observation(context_msg)

    def _inject_plan_step(self):
        """FIX 2: Inject current plan step into conversation."""
        if not self.plan or self.current_plan_step >= len(self.plan):
            return

        step = self.plan[self.current_plan_step]
        step_num = step.get("step", self.current_plan_step + 1)
        action = step.get("action", "?")
        desc = step.get("description", "?")
        target = step.get("target", "")
        expected = step.get("expected_output", "")

        plan_msg = f"CURRENT PLAN STEP {step_num}/{len(self.plan)}: [{action}] {desc}"
        if target:
            plan_msg += f"\nTarget: {target}"
        if expected:
            plan_msg += f"\nExpected outcome: {expected}"

        # FIX 7: Add mode hint
        mode_hint = MODE_SYSTEM_HINTS.get(self.mode, "")
        if mode_hint:
            plan_msg += f"\n\nMODE: {mode_hint}"

        # FIX 8: Add attempt memory (last 3 attempts)
        if self.attempt_history:
            recent = self.attempt_history[-3:]
            history_lines = []
            for a in recent:
                status = "✓" if a["success"] else "✗"
                history_lines.append(
                    f"  {status} Step {a['step']}: {a['tool']} {a['path']} → {a['result_preview'][:80]}"
                )
            plan_msg += f"\n\nPREVIOUS ATTEMPTS:\n" + "\n".join(history_lines)
            if any(not a["success"] for a in recent):
                plan_msg += "\n⚠️ Do NOT repeat failed approaches. Try a different strategy."

        self.messages.append({"role": "user", "content": plan_msg})

    def _inject_error_feedback(self, error_info: dict, raw_error: str):
        """FIX 6: Convert error into structured signal and inject into next prompt."""
        error_type = error_info.get("error_type", "UnknownError")
        suggestion = error_info.get("suggestion", "Review the error and fix it")
        file_hint = error_info.get("file", "")
        line_hint = error_info.get("line", "")

        structured = {
            "type": error_type,
            "file": file_hint,
            "line": line_hint,
            "suggestion": suggestion,
        }

        error_msg = (
            f"ERROR ANALYSIS:\n"
            f"  Type: {error_type}\n"
            f"  File: {file_hint or 'unknown'}\n"
            f"  Line: {line_hint or 'unknown'}\n"
            f"  Suggestion: {suggestion}\n"
            f"\nRaw error:\n{raw_error[:500]}\n"
            f"\nYou MUST fix this error in your next action. "
            f"Read the file first if needed, then apply a targeted fix."
        )

        log("FEEDBACK", f"Error type: {error_type}, suggestion: {suggestion[:100]}")
        self._add_observation(error_msg)

    def _inject_mode_hint(self):
        """FIX 7: Inject a mode-switch hint into the conversation."""
        hint = MODE_SYSTEM_HINTS.get(self.mode, "")
        if hint:
            self._add_observation(f"MODE SWITCH: {hint}")

    def _action_matches_plan(self, tool_name: str, plan_action: str) -> bool:
        """Check if a tool name matches a plan action type."""
        mapping = {
            "read": {"read_file"},
            "edit": {"write_file", "patch_file"},
            "create": {"write_file", "create_file"},
            "run": {"run_code", "run_tests"},
            "test": {"run_tests", "run_code"},
            "search": {"search_files"},
            "analyze": {"read_file", "search_files"},
        }
        return tool_name in mapping.get(plan_action, set())

    # ─── Message Helpers ────────────────────────────────────

    def _add_observation(self, content: str):
        """Add an observation message to the conversation history."""
        self.messages.append({
            "role": "user",
            "content": f"OBSERVATION:\n{content}"
        })

    def _truncate(self, text: str, max_chars: int = MAX_OBSERVATION_CHARS) -> str:
        """Truncate long observations to prevent context overflow."""
        if len(text) <= max_chars:
            return text
        half = max_chars // 2
        return text[:half] + f"\n\n... [{len(text) - max_chars} chars truncated] ...\n\n" + text[-half:]

    # ─── Prompt Building ────────────────────────────────────

    def _build_system_prompt(self, task: str) -> str:
        """Build the system prompt with repo context, tools, and mode."""
        tools_prompt = get_tools_prompt()

        # FIX 7: Mode-specific opening
        mode_hint = MODE_SYSTEM_HINTS.get(self.mode, "")

        return f"""You are an autonomous coding agent. You fix bugs, implement features, and improve code.

{mode_hint}

You work in a STRICT pipeline: PLAN → RETRIEVE → THINK → ACT → OBSERVE → FIX → REPEAT

ALWAYS respond with a JSON object:
{{"thought": "your reasoning", "action": {{"tool": "tool_name", ...}}}}

When done, use:
{{"thought": "task is complete", "action": {{"tool": "done"}}, "summary": "what you did"}}

{tools_prompt}

## STRICT WORKFLOW (MANDATORY)
1. Follow the PLAN step-by-step — do not skip steps
2. ALWAYS read files before editing — NEVER guess file contents
3. Fix ONE issue at a time
4. After editing, ALWAYS verify by running the code
5. If an error occurs, read the error carefully and fix it (minimum {MIN_RETRIES_PER_ERROR} attempts)
6. Signal done ONLY when the task is verified working

## LANGUAGE RULES (CRITICAL)
- ALWAYS match the language to the file extension
- .js files → ONLY JavaScript (use function/const/let, true/false/null, {{ }} blocks)
- .py files → ONLY Python (use def, True/False/None, indentation)
- .html files → ONLY HTML5
- .css files → ONLY CSS
- NEVER write Python syntax (def, range, True/False, None) inside a .js file

## ATTEMPT MEMORY
- Previous attempts and their results will be shown to you
- Do NOT repeat approaches that already failed
- If stuck, try a completely different strategy

## IMPORTANT
- Keep your responses concise
- If a file is HTML/CSS (not executable), verify by reading it back"""

    def _build_task_message(self, task: str) -> str:
        """Build the initial task message with repo map, plan, and context."""
        repo_map = get_repo_map_text(self.repo_analysis)

        file_list = []
        for f in self.repo_analysis.get("files", []):
            rel = f.get("relative_path", f.get("relative", f.get("path", "")))
            lang = f.get("language", "unknown")
            file_list.append(f"  - {rel} ({lang})")

        files_text = "\n".join(file_list) if file_list else "  (empty repository)"

        # FIX 4: Include dependency graph
        dep_text = ""
        if self.dep_graph:
            dep_lines = []
            for src, deps in list(self.dep_graph.items())[:10]:
                if deps:
                    dep_lines.append(f"  {src} → {', '.join(deps[:5])}")
            if dep_lines:
                dep_text = "\n\n## DEPENDENCY GRAPH\n" + "\n".join(dep_lines)

        # FIX 2: Include plan
        plan_text = ""
        if self.plan:
            plan_lines = []
            for s in self.plan:
                step_num = s.get("step", "?")
                action = s.get("action", "?")
                desc = s.get("description", "?")
                target = s.get("target", "")
                expected = s.get("expected_output", "")
                line = f"  {step_num}. [{action}] {desc}"
                if target:
                    line += f" → {target}"
                if expected:
                    line += f" (expected: {expected})"
                plan_lines.append(line)
            plan_text = "\n\n## EXECUTION PLAN (FOLLOW STRICTLY)\n" + "\n".join(plan_lines)

        return f"""## TASK
{task}

## REPOSITORY FILES
{files_text}
{dep_text}

## REPO STRUCTURE
{repo_map[:2000] if repo_map else 'No detailed structure available.'}
{plan_text}

Start by following Step 1 of the plan. Read the relevant files first."""


def run_swe_agent(task: str, repo_path: str, max_steps: int = 15) -> dict:
    """
    Convenience function to run the SWE-agent loop.
    Drop-in compatible with run_agent() signature.
    """
    agent = SWEAgentLoop(repo_path, max_steps=max_steps)
    return agent.run(task)
