import asyncio
import logging
import os
import signal

from hypercorn.asyncio import serve
from hypercorn.config import Config

from .web import create_app


def main() -> None:
    """Serves the app with Hypercorn, which speaks HTTP/2 without TLS (h2c).

    Cloud Run refuses an HTTP/1 request body over 32 MiB before it reaches
    the container; with end-to-end HTTP/2 it sets no size limit (issue #36).
    Hypercorn still answers HTTP/1.1, so a browser, a health check or local
    development need nothing different.
    """
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    config = Config()
    config.bind = [f"0.0.0.0:{int(os.getenv('PORT', '8080'))}"]  # nosec B104
    config.accesslog = None  # request paths can carry file names; never log them
    # Forwarded headers are not trusted: there is no proxy-fix middleware, so
    # the client address is the connecting peer, as before.
    asyncio.run(_serve(config))


async def _serve(config: Config) -> None:
    stop = asyncio.Event()
    try:
        # Cloud Run sends SIGTERM before stopping an instance; finish cleanly.
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    except NotImplementedError:  # Windows has no loop signal handlers
        pass
    await serve(create_app(), config, shutdown_trigger=stop.wait)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
