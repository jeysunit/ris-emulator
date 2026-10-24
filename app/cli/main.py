"""CLI（docs/spec/03_web_cli.md 2 章）.

終了コード：0=正常、1=予期しない誤り、2=設定・入力の誤り、3=予約が無い、4=MWL を待ち受けられない、
5=HL7 の送信先が AE・AR で断った、6=HL7 の送信先と通信できない・ACK を読めない。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

import pydantic

from app import __version__
from app.core.exceptions import (
    ConfigurationError,
    MwlServerError,
    OrderNotFoundError,
    ValidationError,
)
from app.core.hl7 import Hl7Message, build_adt_a08, build_adt_a40, build_orm_o01, visible
from app.core.models import (
    CHARACTER_SET_LABELS,
    STATUS_LABELS,
    CharacterSet,
    Order,
    OrderStatus,
    Patient,
    PersonName,
)
from app.core.mwl_dataset import order_to_dataset
from app.hl7.mllp import send_message
from app.mwl.server import MwlServer
from app.services.config import AppConfig, load_config
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
EXIT_HL7_REJECTED = 5
EXIT_HL7_FAILED = 6
PIR_KINDS = ("a40", "a08", "orm")

EPILOG = """\
例:
  python -m app.cli create CT=3 MR=1
  python -m app.cli create CT=2 --date tomorrow --start 13:00 --patients roster
  python -m app.cli list --date today
  python -m app.cli status RE202610210001 in_progress
  python -m app.cli show RE202610210001
  python -m app.cli retake RE202610210001
  python -m app.cli mwl serve
  python -m app.cli pir send --kind a40 --patient-id RE0000001 --prior-patient-id ER0001 \\
      --name "Yamada^Taro=山田^太郎=やまだ^たろう" --dry-run
  python -m app.cli pir send --kind orm --accession RE202610210001
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="ris-emulator: 開発・試験用の RIS エミュレーター（予約の作成と MWL・MPPS の SCP）",
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
        help="応答の文字コード："
        + "、".join(f"{choice.value}={CHARACTER_SET_LABELS[choice]}" for choice in CharacterSet)
        + "（default: 設定の default_character_set）",
    )
    create.add_argument(
        "--station",
        action="append",
        default=[],
        metavar="NAME",
        help="装置の台帳の名前（モダリティごとに1つ。繰り返せる。default: 台帳の装置を順に使う）",
    )
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

    retake = sub.add_parser(
        "retake",
        parents=[common],
        help="撮り直しの予約を作る（orders.retake_mode が new_order のとき）",
    )
    retake.add_argument("accession_number", help="元の予約の受付番号")
    retake.add_argument("--date", default="", help="予定の日：today・tomorrow・YYYYMMDD（default: 今日）")
    retake.add_argument("--start", default="", help="予定の時刻 HH:MM（default: 今の時刻）")
    retake.add_argument("--json", action="store_true", help="JSON で出す")
    retake.set_defaults(func=retake_command)

    status = sub.add_parser("status", parents=[common], help="予約の状態を変える")
    status.add_argument("accession_number")
    status.add_argument("status", choices=[status.value for status in OrderStatus])
    status.set_defaults(func=status_command)

    mwl = sub.add_parser("mwl", help="MWL・MPPS の SCP")
    mwl_sub = mwl.add_subparsers(dest="mwl_command", required=True)
    serve = mwl_sub.add_parser(
        "serve", parents=[common], help="MWL・MPPS の SCP を起動する（Ctrl+C で止める）"
    )
    serve.set_defaults(func=mwl_serve_command)

    pir = sub.add_parser("pir", help="PIR（Patient Information Reconciliation）の HL7 v2 メッセージ")
    pir_sub = pir.add_subparsers(dest="pir_command", required=True)
    send = pir_sub.add_parser(
        "send",
        parents=[common],
        help="HL7 v2.3.1 のメッセージを組み立て、MLLP で送る",
        description=(
            "a40=患者 ID の統合（ADT^A40）、a08=患者の属性の更新（ADT^A08）、"
            "orm=予約（ORM^O01、ORC-1 は NW）"
        ),
    )
    send.add_argument("--kind", required=True, choices=PIR_KINDS, help="メッセージの種類")
    send.add_argument("--patient-id", help="a40・a08：患者 ID（a40 では統合の後の正式な ID）")
    send.add_argument(
        "--name",
        help='a40・a08：氏名。DICOM の PN の形 "英字=漢字=かな"（各グループは 姓^名^ミドル^接頭辞^接尾辞）',
    )
    send.add_argument("--birth-date", default="", help="a40・a08：生年月日 YYYYMMDD")
    send.add_argument("--sex", default="", choices=("", "M", "F", "O"), help="a40・a08：性別")
    send.add_argument("--prior-patient-id", help="a40：統合される旧い患者 ID（MRG-1）")
    send.add_argument("--prior-name", help="a40：旧い患者の氏名（MRG-7。--name と同じ形）")
    send.add_argument("--accession", help="orm：送る予約の受付番号")
    send.add_argument(
        "--visit-number",
        default="",
        help="PV1-19 の来院番号（a08 は --visit-number か --account-number が要る。"
        "orm の default: 受付番号）",
    )
    send.add_argument("--account-number", default="", help="a08：PID-18 の患者アカウント番号")
    send.add_argument(
        "--patient-class", default="O", help="PV1-2 の患者区分（HL7 Table 0004。default: O=外来、E=救急）"
    )
    send.add_argument("--host", help="送り先のホスト（default: 設定の hl7.host）")
    send.add_argument("--port", type=int, help="送り先のポート（default: 設定の hl7.port）")
    send.add_argument("--dry-run", action="store_true", help="組み立てたメッセージを出すだけで、送らない")
    send.set_defaults(func=pir_send_command)

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
        stations=service.stations_by_name(args.station, list(counts)),
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


def retake_command(args: argparse.Namespace) -> int:
    service = _service(args)
    retake, original = service.create_retake(
        args.accession_number,
        scheduled_date=parse_date_option(args.date, service.today()) if args.date else None,
        start_time=parse_time_option(args.start) if args.start else None,
    )
    if args.json:
        _print_orders([retake], as_json=True)
    else:
        print(
            f"{retake.accession_number}: 撮り直しの予約（元 {original.accession_number}、"
            f"{STATUS_LABELS[original.status]}）"
        )
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


def pir_send_command(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    hl7 = config.hl7
    host = args.host or hl7.host
    port = args.port if args.port is not None else hl7.port
    if not 1 <= port <= 65535:
        raise ValidationError("ポートは 1〜65535 で指定してください")
    message = _build_pir_message(args, config)
    if args.dry_run:
        # 端末に出す表示だけ変える（送る本文は変えない）。入力の氏名などの書式文字も見える形にする
        print("\n".join(visible(line) for line in message.display().splitlines()))
        return EXIT_OK
    result = send_message(message, host, port, hl7.timeout_seconds)
    label = visible(f"{message.message_type}（MSH-10 {message.control_id}）を {host}:{port} へ送りました")
    if result.outcome == "accepted":
        print(f"{label}：受理されました（{result.ack_code}）")
        return EXIT_OK
    reason = f"{result.ack_code}：{result.detail}" if result.ack_code else result.detail
    if result.outcome == "rejected":
        print(f"[ERROR] {label}が、断られました（{visible(reason)}）", file=sys.stderr)
        return EXIT_HL7_REJECTED
    print(f"[ERROR] {message.message_type} を送れませんでした（{visible(reason)}）", file=sys.stderr)
    return EXIT_HL7_FAILED


def _build_pir_message(args: argparse.Namespace, config: AppConfig) -> Hl7Message:
    header = config.hl7.header()
    now = datetime.now()
    if args.kind == "orm":
        if not args.accession:
            raise ValidationError("orm には --accession が要ります")
        order = OrderService(config, today=date.today).get(args.accession)
        return build_orm_o01(
            header,
            order,
            visit_number=args.visit_number or order.accession_number,
            patient_class=args.patient_class,
            now=now,
        )
    if not args.patient_id or not args.name:
        raise ValidationError(f"{args.kind} には --patient-id と --name が要ります")
    patient = _patient_from_args(args)
    namespace = config.orders.issuer_namespace
    if args.kind == "a08":
        return build_adt_a08(
            header,
            patient,
            namespace=namespace,
            visit_number=args.visit_number,
            account_number=args.account_number,
            patient_class=args.patient_class,
            now=now,
        )
    if not args.prior_patient_id:
        raise ValidationError("a40 には --prior-patient-id が要ります")
    return build_adt_a40(
        header,
        patient,
        namespace=namespace,
        prior_patient_id=args.prior_patient_id,
        prior_name=_parse_person_name(args.prior_name) if args.prior_name else None,
        now=now,
    )


def _patient_from_args(args: argparse.Namespace) -> Patient:
    try:
        return Patient(
            patient_id=args.patient_id,
            name=_parse_person_name(args.name),
            birth_date=args.birth_date,
            sex=args.sex,
        )
    except pydantic.ValidationError as exc:
        raise ValidationError(_first_error(exc)) from exc


def _parse_person_name(text: str) -> PersonName:
    """`英字=漢字=かな` を PersonName にする（PS3.5 6.2.1 の PN の形）."""
    groups = text.split("=")
    if len(groups) > 3:
        raise ValidationError("氏名は 英字=漢字=かな の 3 グループまでです", {"value": text})
    try:
        return PersonName(**dict(zip(("alphabetic", "ideographic", "phonetic"), groups)))
    except pydantic.ValidationError as exc:
        raise ValidationError(_first_error(exc)) from exc


def _first_error(exc: pydantic.ValidationError) -> str:
    first = exc.errors()[0]
    return f"{'.'.join(str(part) for part in first['loc'])}: {first['msg']}"


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
        print(f"[ERROR] {visible(str(exc))}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except OrderNotFoundError as exc:
        print(f"[ERROR] {visible(str(exc))}", file=sys.stderr)
        return EXIT_NOT_FOUND
    except MwlServerError as exc:
        print(f"[ERROR] {visible(str(exc))}", file=sys.stderr)
        return EXIT_MWL_ERROR
