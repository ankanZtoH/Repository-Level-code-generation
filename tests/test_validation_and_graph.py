import os
import tempfile
import unittest

from phase2.analyzer import analyze_repo, extract_dependency_graph
from phase2.tools import execute_tool
from utils.executor import run_tests
from utils.file_ops import write_file


class ValidationAndGraphTests(unittest.TestCase):
    def test_run_tests_detects_unittest_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            test_file = os.path.join(tmp, "test_sample.py")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write(
                    "import unittest\n\n"
                    "class SampleTest(unittest.TestCase):\n"
                    "    def test_ok(self):\n"
                    "        self.assertEqual(1 + 1, 2)\n"
                )

            result = run_tests(tmp)

            self.assertEqual(result["returncode"], 0)
            self.assertFalse(result["skipped"])
            self.assertTrue(
                "pytest" in result["command"] or "unittest" in result["command"]
            )

    def test_execute_tool_run_tests_defaults_to_repo_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            test_file = os.path.join(tmp, "test_sample.py")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write(
                    "import unittest\n\n"
                    "class SampleTest(unittest.TestCase):\n"
                    "    def test_ok(self):\n"
                    "        self.assertTrue(True)\n"
                )

            output = execute_tool({"tool": "run_tests"}, tmp)

            self.assertIn("Return code: 0", output)
            self.assertIn("Test command:", output)

    def test_dependency_graph_links_non_python_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = {
                "index.html": '<link href="style.css" rel="stylesheet"><script src="app.js"></script>',
                "style.css": '@import "theme.css";',
                "theme.css": ":root { --x: 1; }",
                "app.js": 'import { add } from "./math.js";\nconst util = require("./util");',
                "math.js": "export function add(a, b) { return a + b; }",
                "util.js": "module.exports = {};",
                "main.c": '#include "math.h"\nint main(void) { return 0; }',
                "math.h": "int add(int a, int b);",
            }
            for rel_path, content in files.items():
                with open(os.path.join(tmp, rel_path), "w", encoding="utf-8") as f:
                    f.write(content)

            analysis = analyze_repo(tmp)
            graph = extract_dependency_graph(tmp, analysis["files"])

            self.assertEqual(set(graph["index.html"]), {"style.css", "app.js"})
            self.assertEqual(set(graph["style.css"]), {"theme.css"})
            self.assertEqual(set(graph["app.js"]), {"math.js", "util.js"})
            self.assertEqual(graph["main.c"], ["math.h"])

    def test_write_file_removes_stale_python_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "sample.py")
            cache_dir = os.path.join(tmp, "__pycache__")
            os.makedirs(cache_dir)
            cache_file = os.path.join(cache_dir, "sample.cpython-314.pyc")
            with open(cache_file, "wb") as f:
                f.write(b"stale")

            self.assertTrue(write_file(source, "VALUE = 1\n"))

            self.assertFalse(os.path.exists(cache_file))


if __name__ == "__main__":
    unittest.main()
