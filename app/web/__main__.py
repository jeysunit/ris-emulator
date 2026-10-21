"""`python -m app.web`：画面と MWL の SCP を起動する（docs/spec/03_web_cli.md 3 章）.

終了コード：0=正常に止めた、2=設定の誤り（127.0.0.1 以外でパスワードが無いなどを含む）、
4=MWL を待ち受けられない。
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from app.core.exceptions import ConfigurationError, MwlServerError
from app.services.config import load_config

from .app import create_app
from .auth import PASSWORD_FILE_ENV, USERNAME, startup_password

DEFAULT_CONFIG = "config/app_config.yaml"
EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_MWL_ERROR = 4

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.web",
        description="ris-emulator の Web 画面と MWL の SCP を起動する（既定は 127.0.0.1:8081 と 127.0.0.1:11112）",
        epilog=(
            f"127.0.0.1 以外で待ち受けるときは {PASSWORD_FILE_ENV} にパスワードのファイルを指す"
            f"（ユーザー名は {USERNAME}）。TLS は手前に置くリバースプロキシで付ける。"
        ),
    )
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG, help=f"設定ファイル（default: {DEFAULT_CONFIG}）"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("pynetdicom").setLevel(logging.WARNING)

    try:
        config = load_config(Path(args.config))
        password = startup_password(config.web.bind_address)
    except ConfigurationError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    # MWL の SCP は uvicorn の前に立てる（待ち受けられなければ画面も起動しない）
    app = create_app(config, password=password, start_mwl=False)
    mwl = app.state.mwl
    if config.web.start_mwl:
        try:
            mwl.start()
        except MwlServerError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return EXIT_MWL_ERROR
    auth = "HTTP Basic" if password is not None else "none (localhost only)"
    logger.info(
        "Web UI on http://%s:%s/ (auth: %s)", config.web.bind_address, config.web.port, auth
    )
    try:
        uvicorn.run(app, host=config.web.bind_address, port=config.web.port, log_level="info")
    finally:
        mwl.stop()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
