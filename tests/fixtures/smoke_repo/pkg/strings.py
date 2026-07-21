"""String helpers used by the cleanup smoke test as a deletion target."""


def reverse_words(sentence: str) -> str:
    """Return the sentence with its whitespace-separated words reversed."""
    return " ".join(reversed(sentence.split()))


def is_palindrome(text: str) -> bool:
    """Return True if text reads the same forwards and backwards."""
    cleaned = "".join(character.lower() for character in text if character.isalnum())
    return cleaned == cleaned[::-1]
