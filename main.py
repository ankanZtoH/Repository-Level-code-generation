#!/usr/bin/env python3
"""
AI Code Agent — Main Entry Point
================================

A controlled semi-autonomous coding agent for Python files.

Usage:
    python main.py                          # Interactive menu
    python main.py phase1 <file> <instr>    # Direct Phase 1 edit (Python only)
    python main.py phase2 <repo> <task>     # Phase 2 agent
    python main.py demo                     # Run demo
"""

import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import OLLAMA_MODEL, DEMO_REPO_DIR
from utils.logger import log, separator, banner
from utils.llm import check_ollama_available
from utils.file_ops import read_file
from phase1.editor import edit_file, edit_code
from phase2.agent import run_agent


# ─── Demo Scenarios (Python only) ──────────────────────────

def demo_phase1_python():
    """Demo: Phase 1 — Direct Python code edit."""
    banner("DEMO: Phase 1 — Python Edit")

    code = '''def greet(name):
    print("hi " + name)

def farewell(name):
    print("bye " + name)
'''
    instruction = (
        "Add type hints, docstrings, and make greet() return a formatted "
        "greeting string with the current time instead of printing. "
        "Add proper error handling for None input."
    )

    result = edit_code(instruction, code, language="python")
    if result:
        separator("Updated Code")
        print(result)
        return True
    return False


def demo_phase2_bugfix():
    """Demo: Phase 2 — Fix the calculator bug using the full agent pipeline."""
    banner("DEMO: Phase 2 — Bug Fix (Calculator)")

    task = (
        "The add() function in calculator.py has a bug — it returns a-b instead of a+b. "
        "Find the bug, fix it, and run the file to verify the fix works. "
        "The expected output of add(2, 3) should be 5."
    )

    result = run_agent(task, DEMO_REPO_DIR)
    separator("Agent Result")
    log("RESULT", f"Success: {result['success']}")
    log("RESULT", f"Steps: {result['steps']}")
    log("RESULT", f"Summary: {result['summary']}")
    return result["success"]


def demo_phase2_feature():
    """Demo: Phase 2 — Add missing features to string_utils.py."""
    banner("DEMO: Phase 2 — Add Features")

    task = (
        "The file string_utils.py has TODO comments for two missing functions:\n"
        "1. is_palindrome(s) — check if a string is a palindrome (ignore case and spaces)\n"
        "2. remove_duplicates(s) — remove duplicate characters while preserving order\n"
        "Implement both functions, add them to the main block for testing, and run the file."
    )

    result = run_agent(task, DEMO_REPO_DIR)
    separator("Agent Result")
    log("RESULT", f"Success: {result['success']}")
    log("RESULT", f"Steps: {result['steps']}")
    log("RESULT", f"Summary: {result['summary']}")
    return result["success"]


# ─── Interactive Menu ───────────────────────────────────────

def interactive_menu():
    """Display interactive menu for demo selection."""
    banner("AI CODE AGENT")
    print("  Controlled semi-autonomous agent for Python code")
    print(f"  Model: {OLLAMA_MODEL}")
    print()

    options = {
        "1": ("Phase 1: Edit Python code",            demo_phase1_python),
        "2": ("Phase 2: Fix calculator bug",           demo_phase2_bugfix),
        "3": ("Phase 2: Add features to string_utils", demo_phase2_feature),
        "4": ("Run ALL demos",                         None),
        "5": ("Custom Phase 1 (provide .py file + instruction)", None),
        "6": ("Custom Phase 2 (provide repo + task)",  None),
    }

    for key, (desc, _) in options.items():
        print(f"  [{key}] {desc}")
    print(f"  [q] Quit")
    print()

    choice = input("Select option: ").strip()

    if choice == "q":
        print("Goodbye!")
        sys.exit(0)
    elif choice == "4":
        run_all_demos()
    elif choice == "5":
        custom_phase1()
    elif choice == "6":
        custom_phase2()
    elif choice in options and options[choice][1]:
        options[choice][1]()
    else:
        print("Invalid option")
        interactive_menu()


def run_all_demos():
    """Run all demo scenarios."""
    banner("RUNNING ALL DEMOS")
    demos = [
        ("Phase 1: Python",           demo_phase1_python),
        ("Phase 2: Bug Fix",          demo_phase2_bugfix),
        ("Phase 2: Add Features",     demo_phase2_feature),
    ]

    results = []
    for name, func in demos:
        separator(f"Running: {name}")
        try:
            success = func()
            results.append((name, success))
        except Exception as e:
            log("ERROR", f"{name} failed: {e}")
            results.append((name, False))

    # Summary
    banner("DEMO RESULTS")
    for name, success in results:
        status = "PASS" if success else "FAIL"
        print(f"  [{status}]  {name}")
    print()


def custom_phase1():
    """Custom Phase 1: User provides Python file and instruction."""
    filepath = input("Python file path (.py): ").strip()
    instruction = input("Edit instruction: ").strip()

    if not filepath or not instruction:
        log("ERROR", "Both file path and instruction are required")
        return

    if not filepath.endswith(".py"):
        log("ERROR", "Only Python (.py) files are supported")
        return

    edit_file(instruction, filepath)


def custom_phase2():
    """Custom Phase 2: User provides repo and task."""
    repo_path = input("Repo path (or press Enter for demo_repo): ").strip()
    if not repo_path:
        repo_path = DEMO_REPO_DIR

    task = input("Task description: ").strip()
    if not task:
        log("ERROR", "Task description is required")
        return

    result = run_agent(task, repo_path)
    separator("Result")
    log("RESULT", f"Success: {result['success']}")
    log("RESULT", f"Summary: {result['summary']}")


# ─── CLI ────────────────────────────────────────────────────

def main():
    """Main entry point with CLI argument support."""
    # Check Ollama
    if not check_ollama_available():
        log("ERROR", "Ollama is not available. Please start Ollama and pull a model:")
        log("INFO", "  1. Install: https://ollama.ai")
        log("INFO", "  2. Start: ollama serve")
        log("INFO", f"  3. Pull model: ollama pull {OLLAMA_MODEL}")
        sys.exit(1)

    log("SYSTEM", f"Ollama connected — model: {OLLAMA_MODEL}")

    args = sys.argv[1:]

    if not args:
        interactive_menu()
        return

    command = args[0].lower()

    if command == "demo":
        run_all_demos()

    elif command == "phase1" and len(args) >= 3:
        filepath = args[1]
        if not filepath.endswith(".py"):
            print("ERROR: Only Python (.py) files are supported")
            sys.exit(1)
        instruction = " ".join(args[2:])
        edit_file(instruction, filepath)

    elif command == "phase2" and len(args) >= 3:
        repo_path = args[1]
        task = " ".join(args[2:])
        result = run_agent(task, repo_path)
        sys.exit(0 if result["success"] else 1)

    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
