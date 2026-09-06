"""Object-store key validation shared by local and GCS backends."""


def check_key(key: str) -> str:
    if not key or key.startswith("/") or ".." in key:
        raise ValueError(f"Invalid object-store key: {key!r}")
    return key


def check_prefix(prefix: str) -> str:
    if prefix.startswith("/") or ".." in prefix:
        raise ValueError(f"Invalid object-store prefix: {prefix!r}")
    return prefix
