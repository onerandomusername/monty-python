from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable, Coroutine, Hashable
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    TypeVar,
    Union,
    overload,
)
from weakref import WeakValueDictionary

from monty.errors import LockedResourceError
from monty.log import get_logger
from monty.utils import function
from monty.utils.function import command_wraps


if TYPE_CHECKING:
    from types import TracebackType

    from typing_extensions import ParamSpec

    P = ParamSpec("P")
    T = TypeVar("T")
    Coro = Coroutine[Any, Any, T]


log = get_logger(__name__)
__lock_dicts = defaultdict(WeakValueDictionary)

_IdCallableReturn = Union[Hashable, Awaitable[Hashable]]
_IdCallable = Callable[[function.BoundArgs], _IdCallableReturn]
ResourceId = Union[Hashable, _IdCallable]


class SharedEvent:
    """
    Context manager managing an internal event exposed through the wait coro.

    While any code is executing in this context manager, the underlying event will not be set;
    when all of the holders finish the event will be set.
    """

    def __init__(self) -> None:
        self._active_count = 0
        self._event = asyncio.Event()
        self._event.set()

    def __enter__(self) -> None:
        """Increment the count of the active holders and clear the internal event."""
        self._active_count += 1
        self._event.clear()

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:  # noqa: ANN001
        """Decrement the count of the active holders; if 0 is reached set the internal event."""
        self._active_count -= 1
        if not self._active_count:
            self._event.set()

    async def wait(self) -> None:
        """Wait for all active holders to exit."""
        await self._event.wait()


@overload
def lock(
    namespace: Hashable,
    resource_id: ResourceId,
    *,
    raise_error: Literal[False] = False,
    wait: bool = ...,
) -> Callable[[Callable[P, Coro[T]]], Callable[P, Coro[T | None]]]: ...


@overload
def lock(
    namespace: Hashable,
    resource_id: ResourceId,
    *,
    raise_error: Literal[True],
    wait: bool = False,
) -> Callable[[Callable[P, Coro[T]]], Callable[P, Coro[T]]]: ...


def lock(
    namespace: Hashable,
    resource_id: ResourceId,
    *,
    raise_error: bool = False,
    wait: bool = False,
) -> Callable[[Callable[P, Coro[T]]], Callable[P, Coro[T | None]]]:
    """
    Turn the decorated coroutine function into a mutually exclusive operation on a `resource_id`.

    If `wait` is True, wait until the lock becomes available. Otherwise, if any other mutually
    exclusive function currently holds the lock for a resource, do not run the decorated function
    and return None.

    If `raise_error` is True, raise `LockedResourceError` if the lock cannot be acquired.

    `namespace` is an identifier used to prevent collisions among resource IDs.

    `resource_id` identifies a resource on which to perform a mutually exclusive operation.
    It may also be a callable or awaitable which will return the resource ID given an ordered
    mapping of the parameters' names to arguments' values.

    If decorating a command, this decorator must go before (below) the `command` decorator.
    """

    def decorator(func: Callable[P, Coro[T]]) -> Callable[P, Coro[T | None]]:
        name = func.__name__

        @command_wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T | None:
            log.trace(f"{name}: mutually exclusive decorator called")

            if callable(resource_id):
                log.trace(f"{name}: binding args to signature")
                bound_args = function.get_bound_args(func, args, kwargs)

                log.trace(f"{name}: calling the given callable to get the resource ID")
                id_ = resource_id(bound_args)

                if inspect.isawaitable(id_):
                    log.trace(f"{name}: awaiting to get resource ID")
                    id_ = await id_
            else:
                id_ = resource_id

            log.trace(f"{name}: getting the lock object for resource {namespace!r}:{id_!r}")

            # Get the lock for the ID. Create a lock if one doesn't exist yet.
            locks = __lock_dicts[namespace]
            lock_ = locks.setdefault(id_, asyncio.Lock())

            # It's safe to check an asyncio.Lock is free before acquiring it because:
            #   1. Synchronous code like `if not lock_.locked()` does not yield execution
            #   2. `asyncio.Lock.acquire()` does not internally await anything if the lock is free
            #   3. awaits only yield execution to the event loop at actual I/O boundaries
            if wait or not lock_.locked():
                log.debug(f"{name}: acquiring lock for resource {namespace!r}:{id_!r}...")
                async with lock_:
                    return await func(*args, **kwargs)
            else:
                log.info(f"{name}: aborted because resource {namespace!r}:{id_!r} is locked")
                if raise_error:
                    raise LockedResourceError(str(namespace), id_)

        return wrapper

    return decorator
