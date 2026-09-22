from enum import StrEnum


class Compatibility(StrEnum):
    NATIVE = "NATIVE"
    SUBSTITUTED = "SUBSTITUTED"
    FLATTENED = "FLATTENED"
    UNSUPPORTED = "UNSUPPORTED"
    IGNORED = "IGNORED"


def emu_to_points(value: str | int) -> float:
    return int(value) / 12700


def warning(code: str, message: str, **context: object) -> dict:
    return {"code": code, "message": message, **context}
