"""GSTIN checksum (mod-36 weighted, as used by GSTN)."""

CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_checksum(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        v = CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += v // 36 + v % 36
    return CHARS[(36 - total % 36) % 36]


def is_valid_gstin(g: str) -> bool:
    return len(g) == 15 and all(c in CHARS for c in g) and gstin_checksum(g[:14]) == g[14]
