def is_palindrome(s):
    return s == s[::-1]
def remove_duplicates(s):
    seen = set()
    return ''.join([c for c in s if not c in seen and not seen.add(c)])
