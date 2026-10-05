"""python -m rastro  →  sobe o servidor (porta 8000, ou PORT)."""

import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run("rastro.app:criar_app", factory=True, host=os.getenv("HOST", "0.0.0.0"),
                port=int(os.getenv("PORT", "8000")), proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
