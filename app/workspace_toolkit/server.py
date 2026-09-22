import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    uvicorn.run(
        "workspace_toolkit.web:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 # nosec B104
        port=int(os.getenv("PORT", "8080")),
        access_log=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
