"""Entry point.

    python -m lowball          run the app
    lowball --demo             run against seeded data, no mod and no network
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .config import DEFAULT_PREFETCH_TAGS, load_settings, save_settings


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    # The uplink logs a line per connect; anything chattier is noise.
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lowball", description="Lowballing assistant")
    parser.add_argument("--data-dir", type=Path, help="where the database and settings live")
    parser.add_argument("--port", type=int, help="uplink port (default 8765)")
    parser.add_argument("--no-prefetch", action="store_true", help="skip the hot-set warm-up")
    parser.add_argument("--demo", action="store_true", help="seed synthetic data and open it")
    parser.add_argument(
        "--listen",
        action="store_true",
        help="print what the mod sends and nothing else; no window, no network",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)

    settings = load_settings()
    if args.data_dir:
        settings.data_dir = args.data_dir
    if args.port:
        settings.uplink_port = args.port
    if not settings.prefetch_tags and not args.no_prefetch:
        settings.prefetch_tags = list(DEFAULT_PREFETCH_TAGS)
    if args.no_prefetch:
        settings.prefetch_tags = []
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if not settings.settings_path.exists():
        save_settings(settings)

    if args.listen:
        # Bringing the mod up for the first time: no Qt, no API calls, no
        # database, so a problem is on one side of the socket or the other.
        from .listen import main as listen_main

        return listen_main(settings.uplink_port)

    if args.demo:
        from .demo import seed_demo_data

        seeded = seed_demo_data(settings)
        logging.getLogger("lowball").info("seeded %d demo events", seeded)

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Lowball")

    from .controller import AppController
    from .ui.main_window import MainWindow
    from .ui.theme import load_fonts

    load_fonts()
    controller = AppController(settings)
    window = MainWindow(controller)
    window.show()
    controller.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
