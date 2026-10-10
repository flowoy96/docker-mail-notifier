import logging

import uvicorn

from . import config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # httpx protokolliert sonst jede Anfrage an die Docker-API.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=config.PORT,
        log_config=None,
        access_log=False,
        server_header=False,
        proxy_headers=config.TRUST_PROXY,
        forwarded_allow_ips="*" if config.TRUST_PROXY else None,
    )


if __name__ == "__main__":
    main()
