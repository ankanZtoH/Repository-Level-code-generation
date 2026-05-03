"""
AI Code Agent — Integration Test Scenarios
Tests the core agent capabilities without requiring Ollama.
Tests the tooling, validation, safe editing, and loop protection.
"""

import os
import sys
import tempfile
import unittest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.validator import validate_syntax
from utils.safe_edit import apply_search_replace, patch_file
from utils.error_handler import analyze_error
from utils.executor import run_code, run_tests, can_execute
from utils.file_ops import write_file, read_file
from phase2.tools import execute_tool, normalize_tool_name
from phase2.agent import LoopProtector


class TestSyntaxValidator(unittest.TestCase):
    """Scenario: Syntax error detection and recovery."""

    def test_valid_python(self):
        valid, err = validate_syntax("x = 1\nprint(x)\n", "test.py")
        self.assertTrue(valid)
        self.assertEqual(err, "")

    def test_invalid_python(self):
        valid, err = validate_syntax("def foo(\n", "test.py")
        self.assertFalse(valid)
        self.assertIn("SyntaxError", err)

    def test_valid_json(self):
        valid, err = validate_syntax('{"key": "value"}', "test.json")
        self.assertTrue(valid)

    def test_invalid_json(self):
        valid, err = validate_syntax('{"key": }', "test.json")
        self.assertFalse(valid)

    def test_bracket_matching(self):
        valid, err = validate_syntax("function f() { return 1; }", "test.js")
        self.assertTrue(valid)

    def test_bracket_mismatch(self):
        valid, err = validate_syntax("function f() { return 1; ", "test.js")
        self.assertFalse(valid)

    def test_empty_content(self):
        valid, err = validate_syntax("", "test.py")
        self.assertFalse(valid)


class TestSafeEdit(unittest.TestCase):
    """Scenario: Safe partial file editing (aider-inspired)."""

    def test_exact_search_replace(self):
        content = "def add(a, b):\n    return a - b\n"
        result = apply_search_replace(content, "return a - b", "return a + b")
        self.assertIn("return a + b", result)
        self.assertIn("def add", result)

    def test_whitespace_flexible_match(self):
        content = "    def add(a, b):\n        return a - b\n"
        search = "def add(a, b):\n    return a - b\n"
        replace = "def add(a, b):\n    return a + b\n"
        result = apply_search_replace(content, search, replace)
        self.assertTrue(result)  # Should find a match
        self.assertIn("a + b", result)

    def test_no_match_returns_empty(self):
        content = "def foo():\n    pass\n"
        result = apply_search_replace(content, "def bar():", "def baz():")
        self.assertEqual(result, "")

    def test_patch_file_with_validation(self):
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("def add(a, b):\n    return a - b\n")
            path = f.name

        try:
            success, msg = patch_file(path, [
                {"search": "return a - b", "replace": "return a + b"}
            ])
            self.assertTrue(success)
            content = read_file(path)
            self.assertIn("return a + b", content)
        finally:
            os.unlink(path)

    def test_patch_file_rejects_bad_syntax(self):
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("x = 1\n")
            path = f.name

        try:
            success, msg = patch_file(path, [
                {"search": "x = 1", "replace": "def broken(\n"}
            ])
            self.assertFalse(success)
            self.assertIn("syntax", msg.lower())
        finally:
            os.unlink(path)


class TestLoopProtector(unittest.TestCase):
    """Scenario: Loop detection and safety limits."""

    def test_detects_stuck_loop(self):
        lp = LoopProtector(max_steps=20, max_retries=3)
        for _ in range(3):
            lp.record("write_file", "calc.py", False)
        self.assertTrue(lp.is_stuck())

    def test_not_stuck_with_different_targets(self):
        lp = LoopProtector(max_steps=20, max_retries=3)
        lp.record("write_file", "a.py", False)
        lp.record("write_file", "b.py", False)
        lp.record("write_file", "c.py", False)
        self.assertFalse(lp.is_stuck())

    def test_limit_reached(self):
        lp = LoopProtector(max_steps=5)
        for i in range(5):
            lp.record("read_file", f"file{i}.py", True)
        self.assertTrue(lp.limit_reached())

    def test_should_stop_on_success(self):
        lp = LoopProtector()
        stop, reason = lp.should_stop(task_complete=True)
        self.assertTrue(stop)
        self.assertIn("completed", reason.lower())

    def test_recovery_suggestion(self):
        lp = LoopProtector()
        lp.record("write_file", "x.py", False)
        self.assertEqual(lp.suggest_recovery(), "read_file")


class TestToolExecution(unittest.TestCase):
    """Scenario: Tool invocation and validation."""

    def test_tool_name_normalization(self):
        self.assertEqual(normalize_tool_name("edit_file"), "patch_file")
        self.assertEqual(normalize_tool_name("run"), "run_code")
        self.assertEqual(normalize_tool_name("test"), "run_tests")

    def test_read_file_tool(self):
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("VALUE = 42\n")
            path = f.name

        try:
            result = execute_tool(
                {"tool": "read_file", "path": path},
                os.path.dirname(path)
            )
            self.assertIn("VALUE = 42", result)
        finally:
            os.unlink(path)

    def test_write_validates_syntax(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = execute_tool(
                {"tool": "write_file", "path": "bad.py", "content": "def broken(\n"},
                tmp
            )
            self.assertIn("Error", result)
            self.assertIn("Syntax", result)

    def test_run_code_captures_output(self):
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("print('hello agent')\n")
            path = f.name

        try:
            result = execute_tool(
                {"tool": "run_code", "path": path},
                os.path.dirname(path)
            )
            self.assertIn("hello agent", result)
            self.assertIn("Return code: 0", result)
        finally:
            os.unlink(path)


class TestErrorAnalysis(unittest.TestCase):
    """Scenario: Error detection and classification."""

    def test_syntax_error(self):
        output = 'File "test.py", line 3\n    def foo(\n         ^\nSyntaxError: unexpected EOF while parsing'
        info = analyze_error(output)
        self.assertEqual(info["type"], "SyntaxError")

    def test_name_error(self):
        output = "NameError: name 'undefined_var' is not defined"
        info = analyze_error(output)
        self.assertEqual(info["type"], "NameError")
        self.assertIn("undefined_var", info["suggestion"])

    def test_import_error(self):
        output = "ModuleNotFoundError: No module named 'nonexistent'"
        info = analyze_error(output)
        self.assertEqual(info["type"], "ImportError")

    def test_type_error(self):
        output = "TypeError: unsupported operand type(s) for +: 'int' and 'str'"
        info = analyze_error(output)
        self.assertEqual(info["type"], "TypeError")

    def test_no_error(self):
        output = "STDOUT:\nhello world\nReturn code: 0"
        info = analyze_error(output)
        self.assertEqual(info["type"], "None")


class TestCodeExecution(unittest.TestCase):
    """Scenario: Code execution and test running."""

    def test_python_execution(self):
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("print(2 + 3)\n")
            path = f.name

        try:
            result = run_code(path)
            self.assertEqual(result["returncode"], 0)
            self.assertIn("5", result["stdout"])
        finally:
            os.unlink(path)

    def test_python_error_captured(self):
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("raise ValueError('test error')\n")
            path = f.name

        try:
            result = run_code(path)
            self.assertNotEqual(result["returncode"], 0)
            self.assertIn("ValueError", result["stderr"])
        finally:
            os.unlink(path)

    def test_can_execute_detection(self):
        self.assertTrue(can_execute("test.py"))
        self.assertTrue(can_execute("test.js"))
        self.assertFalse(can_execute("test.html"))
        self.assertFalse(can_execute("test.css"))

    def test_run_tests_with_unittest(self):
        with tempfile.TemporaryDirectory() as tmp:
            test_file = os.path.join(tmp, "test_sample.py")
            with open(test_file, "w") as f:
                f.write(
                    "import unittest\n\n"
                    "class T(unittest.TestCase):\n"
                    "    def test_ok(self):\n"
                    "        self.assertEqual(1 + 1, 2)\n"
                )
            result = run_tests(tmp)
            self.assertEqual(result["returncode"], 0)


class TestBugFixScenario(unittest.TestCase):
    """Scenario: End-to-end bug detection in demo_repo."""

    def test_demo_repo_has_bug(self):
        """Verify the demo_repo calculator has the expected bug."""
        demo_repo = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "demo_repo"
        )
        calc_path = os.path.join(demo_repo, "calculator.py")
        if not os.path.isfile(calc_path):
            self.skipTest("demo_repo not found")

        result = run_code(calc_path)
        # add(2,3) should output -1 (the bug), not 5
        self.assertIn("-1", result["stdout"])

    def test_demo_repo_tests_fail(self):
        """Verify the demo_repo tests fail due to the calculator bug."""
        demo_repo = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "demo_repo"
        )
        if not os.path.isdir(demo_repo):
            self.skipTest("demo_repo not found")

        result = run_tests(demo_repo)
        # Tests should fail because add() is buggy
        self.assertNotEqual(result["returncode"], 0)


if __name__ == "__main__":
    unittest.main()
