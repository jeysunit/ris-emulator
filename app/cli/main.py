"""CLI（spec/03_web_cli.md 2 章）.

終了コード：0=正常、1=予期しない誤り、2=設定・入力の誤り、3=予約が無い、4=MWL を待ち受けられない。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from app import __version__
from app.core.exceptions import (
    ConfigurationError,
    MwlServerError,
    OrderNotFoundError,
    ValidationError,
)
from app.core.models import STATUS_LABELS, CharacterSet, Order, OrderStatus
from app.core.mwl_dataset import order_to_dataset
from app.mwl.server import MwlServer
from app.services.config import load_config
from app.services.order_service import (
    MAX_INTERVAL_MINUTES,
    OrderRequest,
    OrderService,
    parse_count_spec,
    parse_date_option,
    parse_time_option,
)

DEFAULT_CONFIG = "config/app_config.yaml"
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFIG_ERROR = 2
EXIT_NOT_FOUND = 3
EXIT_MWL_ERROR = 4

EPILOG = """\
例:
  python -m app.cli create CT=3 MR=1
  python -m app.cli create CT=2 --date tomorrow --start 13:00 --patients roster
  python -m app.cli list --date today
  python -m app.cli status RE202610210001 in_progress
  python -m app.cli show RE202610210001
  python -m app.cli mwl serve
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="ris-emulator: 開発・試験用の RIS エミュレーター（予約の作成と MWL の SCP）",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config", default=DEFAULT_CONFIG, help=f"設定ファイル（default: {DEFAULT_CONFIG}）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", parents=[common], help="予約を作る")
    create.add_argument("specs", nargs="+", metavar="MODALITY=COUNT", help="例 CT=3 MR=1")
    create.add_argument("--date", default="today", help="予定の日：today・tomorrow・YYYYMMDD")
    create.add_argument("--start", default="09:00", help="最初の予定の時刻 HH:MM（default: 09:00）")
    create.add_argument("--interval", type=int, default=15, help="予定の間隔（分。default: 15）")
    create.add_argument(
        "--patients", choices=("random", "roster"), default="random", help="患者：乱数か名簿か"
    )
    create.add_argument(
        "--charset",
        choices=[choice.value for choice in CharacterSet],
        help="応答の文字コード（default: 設定の default_character_set）",
    )
    create.add_argument("--station-ae", help="予定の AE タイトル（default: 設定のモダリティごとの値）")
    create.add_argument("--department", help="依頼科（default: 設定の departments から乱数で選ぶ）")
    create.add_argument("--seed", type=int, help="シード（同じシードで同じ患者になる）")
    create.add_argument("--json", action="store_true", help="JSON で出す")
    create.set_defaults(func=create_command)

    listing = sub.add_parser("list", parents=[common], help="予約の一覧")
    listing.add_argument("--date", default="", help="予定の日：today・tomorrow・YYYYMMDD（default: すべて）")
    listing.add_argument(
        "--status", choices=[status.value for status in OrderStatus], help="状態で絞る"
    )
    listing.add_argument("--modality", default="", help="モダリティで絞る")
    listing.add_argument("--json", action="store_true", help="JSON で出す")
    listing.set_defaults(func=list_command)

    show = sub.add_parser("show", parents=[common], help="予約の MWL の応答の全属性を出す")
    show.add_argument("accession_number")
    show.set_defaults(func=show_command)

    status = sub.add_parser("status", parents=[common], help="予約の状態を変える")
    status.add_argument("accession_number")
    status.add_argument("status", choices=[status.value for status in OrderStatus])
    status.set_defaults(func=status_command)

    mwl = sub.add_parser("mwl", help="MWL の SCP")
    mwl_sub = mwl.add_subparsers(dest="mwl_command", required=True)
    serve = mwl_sub.add_parser("serve", parents=[common], help="MWL の SCP を起動する（Ctrl+C で止める）")
    serve.set_defaults(func=mwl_serve_command)

    version = sub.add_parser("version", help="版を出す")
    version.set_defaults(func=version_command)
    return parser


def version_command(args: argparse.Namespace) -> int:
    print(f"ris-emulator {__version__}")
    return EXIT_OK


def create_command(args: argparse.Namespace) -> int:
    service = _service(args)
    counts: dict[str, int] = {}
    for spec in args.specs:
        modality, count = parse_count_spec(spec)
        counts[modality] = counts.get(modality, 0) + count
    if not 0 <= args.interval <= MAX_INTERVAL_MINUTES:
        raise ValidationError(f"間隔は 0〜{MAX_INTERVAL_MINUTES} 分で指定してください")
    request = OrderRequest(
        counts=counts,
        scheduled_date=parse_date_option(args.date, service.today()),
        start_time=parse_time_option(args.start),
        interval_minutes=args.interval,
        patient_source=args.patients,
        character_set=CharacterSet(args.charset) if args.charset else None,
        station_ae_title=args.station_ae,
        department=args.department,
        seed=args.seed,
    )
    orders = service.create_orders(request)
    _print_orders(orders, as_json=args.json)
    return EXIT_OK


def list_command(args: argparse.Namespace) -> int:
    service = _service(args)
    day = parse_date_option(args.date, service.today()).strftime("%Y%m%d") if args.date else ""
    orders = service.list_orders(
        date_from=day,
        date_to=day,
        statuses=[OrderStatus(args.status)] if args.status else None,
        modality=args.modality.upper(),
    )
    _print_orders(orders, as_json=args.json)
    return EXIT_OK


def show_command(args: argparse.Namespace) -> int:
    order = _service(args).get(args.accession_number)
    print(order_to_dataset(order))
    return EXIT_OK


def status_command(args: argparse.Namespace) -> int:
    order = _service(args).set_status(args.accession_number, OrderStatus(args.status))
    print(f"{order.accession_number}: {STATUS_LABELS[order.status]}（{order.status.value}）")
    return EXIT_OK


def mwl_serve_command(args: argparse.Namespace) -> int:
    service = _service(args)
    server = MwlServer(service.config.mwl, service.store)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return EXIT_OK
    return EXIT_OK


def _service(args: argparse.Namespace) -> OrderService:
    config = load_config(Path(args.config))
    return OrderService(config, today=date.today)


def _print_orders(orders: list[Order], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps([order.model_dump(mode="json") for order in orders], ensure_ascii=False, indent=2))
        return
    if not orders:
        print("予約はありません")
        return
    for order in orders:
        patient = order.patient
        print(
            "  ".join(
                (
                    f"{order.scheduled_date} {order.scheduled_time[:2]}:{order.scheduled_time[2:4]}",
                    order.accession_number,
                    order.modality,
                    order.scheduled_station_ae_title,
                    patient.patient_id,
                    patient.name.ideographic.replace("^", " ") or patient.name.alphabetic,
                    order.procedure.name,
                    STATUS_LABELS[order.status],
                )
            )
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("pynetdicom").setLevel(logging.WARNING)
    try:
        return int(args.func(args))
    except (ConfigurationError, ValidationError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except OrderNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_NOT_FOUND
    except MwlServerError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_MWL_ERROR
