"""Broker-free local runner; production uses Celery + Redis with the same SQL job handlers."""

import asyncio
import logging

from .db import initialize
from .jobs import drain
from .pipeline import sweep


async def main():
    initialize()
    logging.basicConfig(level=logging.INFO)
    while True:
        sweep()
        await drain()
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
