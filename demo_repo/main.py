"""Demo repo entry point — imports and uses calculator + string_utils."""

from calculator import add, subtract, multiply, divide
from string_utils import reverse_string, count_vowels
from formatter import format_result, format_table


def main():
    # Calculator demos
    results = [
        ("add(2, 3)", add(2, 3)),
        ("subtract(10, 4)", subtract(10, 4)),
        ("multiply(3, 5)", multiply(3, 5)),
        ("divide(10, 2)", divide(10, 2)),
    ]

    print("=== Calculator ===")
    print(format_table(results))

    # String demos
    print("\n=== String Utils ===")
    print(format_result("reverse('hello')", reverse_string("hello")))
    print(format_result("vowels('hello')", count_vowels("hello")))


if __name__ == "__main__":
    main()
