#!/usr/bin/env python3
"""
AuraCode — Full Project Health Check
Run this to verify everything is working correctly.
"""

import sys
import os
import subprocess

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "

results = []

def check(label, fn):
    try:
        ok, msg = fn()
        results.append((ok, label, msg))
        print(f"  {PASS if ok else FAIL}  {label}: {msg}")
    except Exception as e:
        results.append((False, label, str(e)))
        print(f"  {FAIL}  {label}: {e}")

print("\n" + "="*55)
print("  AuraCode Health Check")
print("="*55)

# ─── Section 1: Imports ──────────────────────────────────
print("\n📦 Imports")

def check_imports():
    from phase2.agent import run_agent, run_agent_swe, LoopProtector
    from phase2.swe_loop import SWEAgentLoop
    from phase2.tools import execute_tool, TOOLS, get_tools_prompt
    from phase2.analyzer import analyze_repo
    from phase2.planner import create_plan
    from utils.validator import validate_syntax
    from utils.safe_edit import apply_search_replace, patch_file
    from utils.error_handler import analyze_error
    from utils.executor import run_code, can_execute
    from utils.llm import query_llm_json, query_llm_chat
    return True, "All modules import OK"

check("Core imports", check_imports)

# ─── Section 2: Validators ───────────────────────────────
print("\n🔍 Validators")

def check_python_validator():
    from utils.validator import validate_syntax
    ok, _ = validate_syntax("def foo(): return 1", "test.py")
    bad, msg = validate_syntax("def broken(", "test.py")
    return (ok and not bad), f"Valid=OK, Invalid=caught ({msg[:40]})"

def check_json_validator():
    from utils.validator import validate_syntax
    ok, _ = validate_syntax('{"key": "value"}', "test.json")
    bad, _ = validate_syntax('{"key": }', "test.json")
    return (ok and not bad), "JSON validation working"

def check_bracket_validator():
    from utils.validator import validate_syntax
    ok, _ = validate_syntax("function f() { return 1; }", "test.js")
    bad, _ = validate_syntax("function f() { return 1;", "test.js")
    return (ok and not bad), "Bracket matching working"

check("Python validator", check_python_validator)
check("JSON validator", check_json_validator)
check("Bracket validator", check_bracket_validator)

# ─── Section 3: Safe Edit ────────────────────────────────
print("\n✏️  Safe Edit (aider-style)")

def check_exact_replace():
    from utils.safe_edit import apply_search_replace
    result = apply_search_replace("return a - b", "return a - b", "return a + b")
    return result == "return a + b", "Exact match replacement"

def check_patch_file():
    import tempfile
    from utils.safe_edit import patch_file
    from utils.file_ops import read_file
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("def add(a, b):\n    return a - b\n")
        path = f.name
    try:
        ok, msg = patch_file(path, [{"search": "return a - b", "replace": "return a + b"}])
        content = read_file(path)
        return ok and "a + b" in content, msg
    finally:
        os.unlink(path)

check("Exact search/replace", check_exact_replace)
check("patch_file with validation", check_patch_file)

# ─── Section 4: Loop Protector ──────────────────────────
print("\n🛡️  Loop Protection (mini-swe-agent style)")

def check_stuck_detection():
    from phase2.agent import LoopProtector
    lp = LoopProtector(max_steps=20, max_retries=3)
    for _ in range(3):
        lp.record("write_file", "x.py", False)
    return lp.is_stuck(), f"Detects 3 repeated failures"

def check_step_limit():
    from phase2.agent import LoopProtector
    lp = LoopProtector(max_steps=5)
    for i in range(5):
        lp.record("read_file", f"file{i}.py", True)
    return lp.limit_reached(), "Step limit enforced"

def check_stop_signal():
    from phase2.agent import LoopProtector
    lp = LoopProtector()
    stop, reason = lp.should_stop(task_complete=True)
    return stop and "completed" in reason.lower(), reason

check("Stuck detection", check_stuck_detection)
check("Step limit", check_step_limit)
check("Stop signal", check_stop_signal)

# ─── Section 5: Error Analysis ──────────────────────────
print("\n🔬 Error Analysis")

def check_error_types():
    from utils.error_handler import analyze_error
    cases = [
        ('SyntaxError: invalid syntax', 'SyntaxError'),
        ("NameError: name 'x' is not defined", 'NameError'),
        ("ModuleNotFoundError: No module named 'foo'", 'ImportError'),
        ("TypeError: unsupported operand", 'TypeError'),
        ("Return code: 0", 'None'),
    ]
    for text, expected in cases:
        result = analyze_error(text)
        if result["type"] != expected:
            return False, f"Expected {expected}, got {result['type']}"
    return True, f"All {len(cases)} error types detected correctly"

check("Error type detection", check_error_types)

# ─── Section 6: Code Execution ──────────────────────────
print("\n⚡ Code Execution")

def check_python_run():
    import tempfile
    from utils.executor import run_code
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("print(2 + 3)\n")
        path = f.name
    try:
        result = run_code(path)
        return result["returncode"] == 0 and "5" in result["stdout"], \
               f"returncode={result['returncode']}, output={result['stdout'].strip()}"
    finally:
        os.unlink(path)

def check_demo_repo_bug():
    from utils.executor import run_code
    calc_path = os.path.join(os.path.dirname(__file__), "demo_repo", "calculator.py")
    if not os.path.isfile(calc_path):
        return True, "demo_repo not found — skipped"
    result = run_code(calc_path)
    has_bug = "-1" in result["stdout"]
    return has_bug, f"Bug confirmed: add(2,3)=-1 in output"

check("Python execution", check_python_run)
check("demo_repo bug exists", check_demo_repo_bug)

# ─── Section 7: Tools ───────────────────────────────────
print("\n🔧 Tool Registry")

def check_tools():
    from phase2.tools import TOOLS, normalize_tool_name, get_tools_prompt
    required = ["read_file", "write_file", "run_code", "run_tests", "search_files", "patch_file"]
    missing = [t for t in required if t not in TOOLS]
    if missing:
        return False, f"Missing tools: {missing}"
    assert normalize_tool_name("edit_file") == "patch_file"
    assert normalize_tool_name("run") == "run_code"
    prompt = get_tools_prompt()
    return len(prompt) > 100, f"6 tools registered, prompt={len(prompt)} chars"

check("Tool registry", check_tools)

# ─── Section 8: SWE Loop ────────────────────────────────
print("\n🤖 SWE-Agent Loop")

def check_swe_imports():
    from phase2.swe_loop import SWEAgentLoop, run_swe_agent
    from phase2.agent import run_agent_swe
    from utils.llm import query_llm_chat
    return True, "SWE loop imports OK"

def check_message_history():
    from phase2.swe_loop import SWEAgentLoop
    agent = SWEAgentLoop(".", max_steps=5)
    agent.messages = [{"role": "system", "content": "test"}]
    agent._add_observation("Test observation")
    return (
        len(agent.messages) == 2
        and agent.messages[1]["role"] == "user"
        and "OBSERVATION" in agent.messages[1]["content"]
    ), f"History grows correctly: {len(agent.messages)} messages"

def check_truncation():
    from phase2.swe_loop import SWEAgentLoop
    agent = SWEAgentLoop(".", max_steps=5)
    long_text = "x" * 10000
    truncated = agent._truncate(long_text, max_chars=3000)
    return len(truncated) < 4000 and "truncated" in truncated, \
           f"Truncated {len(long_text)} → {len(truncated)} chars"

check("SWE loop imports", check_swe_imports)
check("Message history accumulation", check_message_history)
check("Observation truncation", check_truncation)

# ─── Section 9: Ollama Status ───────────────────────────
print("\n🦙 Ollama / LLM")

def check_ollama():
    from utils.llm import check_ollama_available
    import config
    available = check_ollama_available()
    return available, f"Model: {config.OLLAMA_MODEL} at {config.OLLAMA_BASE_URL}"

check("Ollama connection", check_ollama)

# ─── Summary ────────────────────────────────────────────
total = len(results)
passed = sum(1 for ok, _, _ in results if ok)
failed = total - passed

print("\n" + "="*55)
print(f"  Results: {passed}/{total} checks passed", PASS if failed == 0 else FAIL)
if failed > 0:
    print("\n  Failed checks:")
    for ok, label, msg in results:
        if not ok:
            print(f"    {FAIL} {label}: {msg}")
print("="*55 + "\n")

sys.exit(0 if failed == 0 else 1)
