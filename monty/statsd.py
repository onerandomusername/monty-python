import asyncio
import socket
from typing import cast

from statsd.client.base import StatsClientBase

from monty.utils import scheduling


class AsyncStatsClient(StatsClientBase):
    """An async transport method for statsd communication."""

    def __init__(self, *, host: str, port: int, prefix: str = None) -> None:
        """Create a new client."""
        self._addr = (socket.gethostbyname(host), port)
        self._prefix = prefix
        self._transport = None
        self._loop = asyncio.get_running_loop()
        scheduling.create_task(self.create_socket())

    async def create_socket(self) -> None:
        """Use the loop.create_datagram_endpoint method to create a socket."""
        transport, _ = await self._loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, family=socket.AF_INET, remote_addr=self._addr
        )
        self._transport = cast(asyncio.DatagramTransport, transport)

    def _send(self, data: str) -> None:
        """Start an async task to send data to statsd."""
        scheduling.create_task(self._async_send(data))

    async def _async_send(self, data: str) -> None:
        """Send data to the statsd server using the async transport."""
        assert self._transport
        self._transport.sendto(data.encode("utf-8"), self._addr)
