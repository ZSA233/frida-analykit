from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial
from typing import TypeVar

T = TypeVar("T")


async def to_thread(callable_obj: Callable[..., T], /, *args: object, **kwargs: object) -> T:
    return await asyncio.to_thread(partial(callable_obj, *args, **kwargs))
