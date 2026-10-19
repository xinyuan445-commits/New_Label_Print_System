"""Account identifiers accepted by the local label-printing system."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

_LOGIN_RE = re.compile(r"[\w.@+%\-]+", re.UNICODE)


def _validate_login(value: str) -> str:
    if not _LOGIN_RE.fullmatch(value):
        raise ValueError("account name contains invalid characters")
    return value.lower()


LoginName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=254),
    AfterValidator(_validate_login),
]
