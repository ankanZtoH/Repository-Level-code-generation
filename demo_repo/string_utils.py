"""
Demo Repo — String utilities with a missing feature
"""


def reverse_string(s):
    """Reverse a string."""
    return s[::-1]


def count_vowels(s):
    """Count vowels in a string."""
    return sum(1 for c in s.lower() if c in "aeiou")


def capitalize_words(s):
    """Capitalize the first letter of each word."""
    return s.title()


# TODO: Add a function to check if a string is a palindrome
# TODO: Add a function to remove duplicate characters


if __name__ == "__main__":
    test = "hello world"
    print(f"Original: {test}")
    print(f"Reversed: {reverse_string(test)}")
    print(f"Vowels: {count_vowels(test)}")
    print(f"Capitalized: {capitalize_words(test)}")
