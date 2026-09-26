"""Broker-free local runner; production uses Celery + Redis with the same SQL job handlers."""

import asyncio
import logging

from .db import initialize
from .jobs import drain
from .pipeline import sweep

log = logging.getLogger("clipbot.worker")


async def run(stop=None):
    """Sweep for due work and run it every few seconds until `stop` (a threading.Event) is set.

    The desktop app runs this in a background thread next to the API."""
    stopping = stop.is_set if stop else (lambda: False)
    while not stopping():
        try:
            sweep()
            await drain(stopping=stopping)
        except Exception:
            # One bad pass (e.g. the database is briefly locked) mustn't stop the worker for good.
            log.exception("Worker pass failed; trying again shortly")
        for _ in range(5):
            if stopping():
                return
            await asyncio.sleep(1)


async def main():
    initialize()
    logging.basicConfig(level=logging.INFO)
    await run()


if __name__ == "__main__":
    asyncio.run(main())
