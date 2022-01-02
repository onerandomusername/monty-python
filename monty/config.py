"""Client for worker which stores keys and values..."""

import asyncio
import json

import aiohttp

from monty.constants import Database as DatabaseConstant


class Database:
    """Client for the "database"."""

    def __init__(self):
        self.is_ready = asyncio.Event()

        self.http: aiohttp.ClientSession = None

    async def async_init(self) -> None:
        """Init asynchronous bits."""
        self.http = aiohttp.ClientSession(
            base_url=DatabaseConstant.url,
            headers={
                "Authorization": f"Bearer {DatabaseConstant.auth_token}",
            },
            raise_for_status=False,
        )
        self.is_ready.set()

    async def put_keys(self, **keys) -> tuple[int, dict[str]]:
        """Set keys to kw=arg."""
        await self.is_ready.wait()

        async with self.http.put("/", json={"config": keys}, raise_for_status=False) as resp:
            return resp.status, await resp.json()

    async def fetch_keys(self, *keys) -> tuple[int, dict[str]]:
        """Fetch the provided keys."""
        await self.is_ready.wait()

        params = {"json": json.dumps({"config": keys}, separators=(",", ":"), indent=False).replace("\n", "")}
        async with self.http.get("/get", params=params) as resp:
            return resp.status, await resp.json()

    async def delete_keys(self, *keys) -> tuple[int, dict[str]]:
        """Delete the provides keys."""
        await self.is_ready.wait()

        async with self.http.delete("/", json={"config": keys}) as resp:
            return resp.status, await resp.json()

    async def list_keys(self, query: str = "*") -> tuple[int, dict[str]]:
        """Search for the provided query. No query will return up to 1000 existing keys."""
        await self.is_ready.wait()
        async with self.http.get("/list", params={"query": query}) as resp:
            return resp.status, await resp.json()

    async def close(self) -> None:
        """Close the http session."""
        self.is_ready.clear()
        await self.http.close()


if __name__ == "__main__":
    print("running methods as a test!")

    async def main() -> None:
        """Run the requests as a test."""
        db = Database()
        try:
            print("GET", await db.fetch_keys("hello"))
            print("PUT", await db.put_keys(hello="world", hi="earth"))
            print("GET", await db.fetch_keys("hello"))
            print("LIST", await db.list_keys("hi"))
            print("LIST", await db.list_keys("hello"))
            print("DELETE", await db.delete_keys("hello"))
            print("GET", await db.fetch_keys("hello"))
            print("LIST", await db.list_keys())
        finally:
            await db.close()

    asyncio.run(main())
