import asyncio
import socket

from statsd.client.base import StatsClientBase


class AsyncStatsClient(StatsClientBase):
    """An async transport method for statsd communication."""

    def __init__(self, *, host: str, port: int, prefix: str = None):
        """Create a new client."""
        _, _, _, _, addr = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)[0]
        self._addr = addr
        self._prefix = prefix
        self._transport = None
        self._loop = asyncio.get_running_loop()
        self._loop.create_task(self.create_socket())

    async def create_socket(self) -> None:
        """Use the loop.create_datagram_endpoint method to create a socket."""
        self._transport, _ = await self._loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, family=socket.AF_INET, remote_addr=self._addr
        )

    def _send(self, data: str) -> None:
        """Start an async task to send data to statsd."""
        self._loop.create_task(self._async_send(data))

    async def _async_send(self, data: str) -> None:
        """Send data to the statsd server using the async transport."""
        self._transport.sendto(data.encode("utf-8"), self._addr)
