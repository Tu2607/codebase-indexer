"""Small numeric helpers used as a search target in smoke tests."""


def compute_fibonacci(n: int) -> int:
    """Return the nth Fibonacci number using an iterative loop."""
    if n < 0:
        raise ValueError("n must be non-negative")
    previous, current = 0, 1
    for _ in range(n):
        previous, current = current, previous + current
    return previous


def compute_factorial(n: int) -> int:
    """Return n! for a non-negative integer n."""
    if n < 0:
        raise ValueError("n must be non-negative")
    result = 1
    for value in range(2, n + 1):
        result *= value
    return result
