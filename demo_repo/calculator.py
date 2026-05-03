"""Calculator module — has a deliberate bug in add()."""


def add(a, b):
    return a - b  # BUG: should be a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


if __name__ == "__main__":
    print(f"add(2, 3) = {add(2, 3)}")
    print(f"subtract(10, 4) = {subtract(10, 4)}")
    print(f"multiply(3, 5) = {multiply(3, 5)}")
    print(f"divide(10, 2) = {divide(10, 2)}")
