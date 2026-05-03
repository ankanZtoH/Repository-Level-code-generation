"""String utility functions — some are TODO stubs."""


def reverse_string(s):
    """Reverse a string."""
    return s[::-1]


def count_vowels(s):
    """Count vowels in a string."""
    return sum(1 for c in s.lower() if c in "aeiou")


def is_palindrome(s):
    """Check if a string is a palindrome (ignore case and spaces)."""
    # TODO: implement this function
    pass


def remove_duplicates(s):
    """Remove duplicate characters while preserving order."""
    # TODO: implement this function
    pass


if __name__ == "__main__":
    print(f"reverse_string('hello') = {reverse_string('hello')}")
    print(f"count_vowels('hello world') = {count_vowels('hello world')}")
    print(f"is_palindrome('racecar') = {is_palindrome('racecar')}")
    print(f"remove_duplicates('aabbcc') = {remove_duplicates('aabbcc')}")
