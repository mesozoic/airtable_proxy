"""Shared helpers for routes that read from local storage."""

from typing import Any


def is_empty_value(value: Any) -> bool:
    """
    Check if a value is considered "empty" by Airtable.

    Airtable omits fields with empty values (None, "", [], False) from responses.
    """
    if value is None:
        return True
    if value == "":
        return True
    if value == []:
        return True
    if value is False:
        return True
    return False
