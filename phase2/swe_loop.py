"""
AI Code Agent — SWE-Agent Conversational Loop
==============================================

Implements the core SWE-agent pattern: a multi-turn conversation where the LLM
accumulates context across steps and chooses its own tools.

Adapted from mini-swe-agent's DefaultAgent.run() architecture:
  - Message history grows with each step (THOUGHT + OBSERVATION)
  - LLM sees ALL previous steps when deciding next action
  - Step/cost limits prevent runaway execution
  - Observations are truncated to fit context window

This is the KEY difference from the old one-shot approach:
  Old: Each step is an independent LLM call with no memory
  New: Each step sees everything that happened before it
"""

import os
import json
from utils.logger import log, separator
from utils.llm import query_llm_chat
from utils.file_ops import read_file
from utils.error_handler import analyze_error
from utils.validator import validate_syntax
from phase2.tools import execute_tool, get_tools_prompt, normalize_tool_name
from phase2.analyzer import analyze_repo, get_repo_map_text
from phase2.agent import LoopProtector

# Maximum characters per observation to prevent context overflow
MAX_OBSERVATION_CHARS = 3000


class SWEAgentLoop:
    """
    SWE-agent style conversational loop.
    The LLM accumulates context and chooses its own tools.
    """

    def __init__(self, repo_path: str, max_steps: int = 15):
        self.repo_path = os.path.abspath(repo_path)
        self.max_steps = max_steps
        self.messages = []
        self.protector = LoopProtector(max_steps=max_steps)
        self.files_modified = []
        self.step_count = 0

    def run(self, task: str) -> dict:
        """
        Run the SWE-agent loop.
        Returns: {"success": bool, "summary": str, "steps": int}
        """
        separator("SWE-AGENT START")
        log("PLAN", f"Task: {task}")

        # Step 1: Build system prompt with repo context + tool descriptions
        system_prompt = self._build_system_prompt()

        # Step 2: Build initial user message with task + repo map
        user_message = self._build_task_message(task)

        # Step 3: Initialize message history
        self.messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        log("THOUGHT", f"System prompt: {len(system_prompt)} chars, "
            f"Task message: {len(user_message)} chars")

        # Step 4: Run the loop
        result = {"success": False, "summary": "Agent did not complete", "steps": 0}

        while self.step_count < self.max_steps:
            step_result = self._step()

            if step_result == "done":
                result["success"] = True
                result["summary"] = f"Completed in {self.step_count} steps. " \
                                    f"Modified: {', '.join(self.files_modified) or 'none'}"
                break
            elif step_result == "error":
                # Continue — the error observation is in history, LLM can recover
                pass
            elif step_result == "stop":
                result["summary"] = f"Stopped after {self.step_count} steps: " \
                                    f"{self.protector.should_stop()[1]}"
                break

        result["steps"] = self.step_count
        log("RESULT" if result["success"] else "ERROR", result["summary"])
        return result

    def _step(self) -> str:
        """
        Execute one step of the SWE-agent loop:
          1. Query LLM with full message history
          2. Parse the response (thought + action)
          3. Execute the action
          4. Add observation to history
          5. Check if done

        Returns: "done", "continue", "error", or "stop"
        """
        self.step_count += 1

        # Check limits
        stop, reason = self.protector.should_stop()
        if stop:
            log("ERROR", f"Loop halted: {reason}")
            return "stop"

        separator(f"Step {self.step_count}")

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
            self._add_observation("Error: Your response was not valid JSON. "
                                  "Please respond with a JSON object containing 'thought' and 'action'.")
            self.protector.record("query", "llm", False)
            return "error"

        # Add assistant message to history
        self.messages.append({
            "role": "assistant",
            "content": raw_response
        })

        # Extract thought
        thought = response.get("thought", "")
        if thought:
            log("THOUGHT", thought[:200])

        # Extract action
        action = response.get("action", {})
        if not action:
            self._add_observation("Error: No 'action' field in your response. "
                                  "Include an action like {\"tool\": \"read_file\", \"path\": \"file.py\"}")
            self.protector.record("query", "llm", False)
            return "error"

        tool_name = normalize_tool_name(action.get("tool", ""))

        # 3. Check if done
        if tool_name == "done" or action.get("tool", "").lower() == "done":
            summary = response.get("summary", thought or "Task completed")
            log("RESULT", f"Agent signals done: {summary}")
            return "done"

        # 4. Execute the action
        log("ACTION", f"Step {self.step_count}: {tool_name} "
            f"{action.get('path', '')}")

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

        # 5. Add observation to history (truncated)
        truncated = self._truncate(observation)
        log("OBSERVATION", truncated[:300])
        self._add_observation(truncated)

        return "continue"

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

    def _build_system_prompt(self) -> str:
        """Build the system prompt with repo context and tool descriptions."""
        tools_prompt = get_tools_prompt()

        return f"""You are an autonomous coding agent. You fix bugs, implement features, and improve code.

You work step-by-step: THINK about what to do, then take an ACTION using a tool, then observe the result.

ALWAYS respond with a JSON object:
{{"thought": "your reasoning", "action": {{"tool": "tool_name", ...}}}}

When done, use:
{{"thought": "task is complete", "action": {{"tool": "done"}}, "summary": "what you did"}}

{tools_prompt}

## WORKFLOW
1. Read files to understand the codebase
2. Identify the problem
3. Make targeted fixes (prefer patch_file over write_file)
4. Run code to verify
5. Signal done when fixed

## LANGUAGE RULES (CRITICAL)
- ALWAYS match the language to the file extension
- .js files → ONLY JavaScript (use function/const/let, true/false/null, {{ }} blocks)
- .py files → ONLY Python (use def, True/False/None, indentation)
- .html files → ONLY HTML5
- .css files → ONLY CSS
- NEVER write Python syntax (def, range, True/False, None) inside a .js file
- NEVER write JavaScript syntax (function, const, let) inside a .py file

## IMPORTANT
- Read before editing — NEVER guess file contents
- Fix ONE issue at a time
- After editing, always verify by running the code
- If a file is HTML/CSS (not executable), verify by reading it back
- Keep your responses concise"""

    def _build_task_message(self, task: str) -> str:
        """Build the initial task message with repo map."""
        # Analyze repo to get file list
        repo_analysis = analyze_repo(self.repo_path)
        repo_map = get_repo_map_text(repo_analysis)

        file_list = []
        for f in repo_analysis.get("files", []):
            rel = f.get("relative_path", f.get("path", ""))
            lang = f.get("language", "unknown")
            file_list.append(f"  - {rel} ({lang})")

        files_text = "\n".join(file_list) if file_list else "  (empty repository)"

        return f"""## TASK
{task}

## REPOSITORY FILES
{files_text}

## REPO STRUCTURE
{repo_map[:2000] if repo_map else 'No detailed structure available.'}

Start by reading the relevant files to understand the codebase. Then fix the issue."""


def run_swe_agent(task: str, repo_path: str, max_steps: int = 15) -> dict:
    """
    Convenience function to run the SWE-agent loop.
    Drop-in compatible with run_agent() signature.
    """
    agent = SWEAgentLoop(repo_path, max_steps=max_steps)
    return agent.run(task)
