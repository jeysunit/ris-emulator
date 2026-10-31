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
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

import pydantic

from app.core.exceptions import (
    ConfigurationError,
    MppsNotFoundError,
    MwlServerError,
    OrderNotFoundError,
    ReconciliationNotFoundError,
    ValidationError,
)
from app.core.hl7 import (
    ORDER_CONTROLS,
    Hl7Message,
    build_adt_a08,
    build_adt_a40,
    build_orm_o01,
    visible,
)
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
from app.core.patient_input import (
    SCRIPT_LABELS,
    birth_date_from_cli,
    check_name_group,
    to_katakana,
    validate_patient_id_input,
    validate_sex,
)
from app.core.reconciliation import DELIVERY_LABELS
from app.hl7.mllp import send_message
from app.mwl.server import MwlServer
from app.services.config import AppConfig, OrdersConfig, load_config
from app.services.order_service import (
    MAX_INTERVAL_MINUTES,
    OrderRequest,
    OrderService,
    parse_count_spec,
    parse_date_option,
    parse_time_option,
)
from app.services.reconciliation import ReconcileRequest, ReconciliationService
from app.services.store import Reconciliation
from app.version import app_version

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
            "a40=患者ID の統合（ADT^A40）、a08=患者の属性の更新（ADT^A08）、"
            "orm=予約（ORM^O01。ORC-1 は --order-control）"
        ),
    )
    send.add_argument("--kind", required=True, choices=PIR_KINDS, help="メッセージの種類")
    send.add_argument("--patient-id", help="a40・a08：患者ID（a40 では統合の後の正式な ID）")
    send.add_argument(
        "--name",
        help='a40・a08：氏名。DICOM の PN の形 "英字=漢字=かな"（各グループは 姓^名^ミドル^接頭辞^接尾辞）',
    )
    send.add_argument("--birth-date", default="", help="a40・a08：生年月日 YYYYMMDD（1975/05/14・S50/05/14 の形も受ける）")
    send.add_argument("--sex", default="U", choices=("", "M", "F", "O", "U"), help="a40・a08：性別")
    send.add_argument("--prior-patient-id", help="a40：統合される旧い患者ID（MRG-1）")
    send.add_argument("--prior-name", help="a40：旧い患者の氏名（MRG-7。--name と同じ形）")
    send.add_argument("--accession", help="orm：送る予約の受付番号")
    send.add_argument(
        "--order-control",
        choices=ORDER_CONTROLS,
        default="NW",
        help="orm：ORC-1（NW=予約、CA=取消、DC=中止、XO=変更。default: NW）",
    )
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

    reconcile = sub.add_parser(
        "reconcile", help="照合：予約の無い撮影に、正式な患者と予約を結び、HL7 で知らせる"
    )
    reconcile_sub = reconcile.add_subparsers(dest="reconcile_command", required=True)
    reconcile_list = reconcile_sub.add_parser(
        "list", parents=[common], help="予約に結び付かなかった撮影（MPPS）の一覧"
    )
    reconcile_list.add_argument("--json", action="store_true", help="JSON で出す")
    reconcile_list.set_defaults(func=reconcile_list_command)
    run = reconcile_sub.add_parser(
        "run",
        parents=[common],
        help="撮影に正式な患者と新しい予約を結び、HL7 を送る",
        description="正式な患者は --roster-patient-id（名簿）か、--patient-id と --name（入力）で指定する",
    )
    run.add_argument("sop_instance_uid", help="撮影（MPPS）の SOP Instance UID（reconcile list で見る）")
    run.add_argument("--roster-patient-id", help="名簿の患者の ID")
    run.add_argument("--patient-id", help="正式な患者ID")
    run.add_argument("--name", help='正式な氏名。DICOM の PN の形 "英字=漢字=かな"')
    run.add_argument("--birth-date", default="", help="生年月日 YYYYMMDD（1975/05/14・S50/05/14 の形も受ける）")
    run.add_argument("--sex", default="U", choices=("", "M", "F", "O", "U"), help="性別")
    run.add_argument("--procedure", help="検査の種類のコード（default: モダリティの先頭）")
    run.add_argument("--department", help="依頼科（default: 救急科。設定に無ければ先頭）")
    run.add_argument("--json", action="store_true", help="JSON で出す")
    run.set_defaults(func=reconcile_run_command)
    resend = reconcile_sub.add_parser(
        "resend", parents=[common], help="受理されていない HL7 を、同じ本文で順に送り直す"
    )
    resend.add_argument("accession_number", help="照合で作った予約の受付番号")
    resend.add_argument("--json", action="store_true", help="JSON で出す")
    resend.set_defaults(func=reconcile_resend_command)

    version = sub.add_parser("version", help="版を出す")
    version.set_defaults(func=version_command)
    return parser


def version_command(args: argparse.Namespace) -> int:
    print(f"ris-emulator {app_version()}")
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
    order, result = ReconciliationService(_service(args)).set_status(
        args.accession_number, OrderStatus(args.status)
    )
    print(f"{order.accession_number}: {STATUS_LABELS[order.status]}（{order.status.value}）")
    if result is not None:
        return _print_reconciliation(result, as_json=False)
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
    if args.order_control != "NW" and args.kind != "orm":
        raise ValidationError("--order-control は orm だけで使います")
    if args.kind == "orm":
        if not args.accession:
            raise ValidationError("orm には --accession が要ります")
        order = OrderService(config, today=date.today).get(args.accession)
        return build_orm_o01(
            header,
            order,
            visit_number=args.visit_number or order.accession_number,
            patient_class=args.patient_class,
            order_control=args.order_control,
            now=now,
        )
    if not args.patient_id or not args.name:
        raise ValidationError(f"{args.kind} には --patient-id と --name が要ります")
    patient = _patient_from_args(args, config.orders)
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
        prior_name=(
            _parse_person_name(args.prior_name, config.orders) if args.prior_name else None
        ),
        now=now,
    )


def _patient_from_args(args: argparse.Namespace, orders: OrdersConfig) -> Patient:
    # pydantic の英語の文より先に、日本語の文で断る（入力の確かめは app/core/patient_input.py）
    validate_patient_id_input(args.patient_id)
    name = _parse_person_name(args.name, orders)
    birth_date = birth_date_from_cli(args.birth_date)
    validate_sex(args.sex)
    try:
        return Patient(
            patient_id=args.patient_id,
            name=name,
            birth_date=birth_date,
            sex=args.sex,
        )
    except pydantic.ValidationError as exc:
        raise ValidationError(_first_error(exc)) from exc


def _parse_person_name(text: str, orders: OrdersConfig) -> PersonName:
    """`英字=漢字=かな` を PersonName にする（PS3.5 6.2.1 の PN の形）。かなのひらがなはカタカナに直す."""
    groups = text.split("=")
    if len(groups) > 3:
        raise ValidationError("氏名は 英字=漢字=かな の 3 グループまでです", {"value": text})
    if len(groups) == 3 and not orders.patient_input_test_mode:
        groups[2] = to_katakana(groups[2])
    for (script, label), group in zip(SCRIPT_LABELS.items(), groups):
        message = check_name_group(
            script,
            label,
            group,
            orders.default_character_set,
            test_mode=orders.patient_input_test_mode,
        )
        if message:
            raise ValidationError(message)
    try:
        return PersonName(**dict(zip(("alphabetic", "ideographic", "phonetic"), groups)))
    except pydantic.ValidationError as exc:
        raise ValidationError(_first_error(exc)) from exc


def _first_error(exc: pydantic.ValidationError) -> str:
    first = exc.errors()[0]
    return f"{'.'.join(str(part) for part in first['loc'])}: {first['msg']}"


def reconcile_list_command(args: argparse.Namespace) -> int:
    items = ReconciliationService(_service(args)).list_unreconciled()
    if args.json:
        rows = [
            {
                "sop_instance_uid": item.sop_instance_uid,
                "status": item.status,
                "received_at": item.received_at,
                "patient_id": item.patient.patient_id,
                "patient_name": item.patient.name.to_dicom(),
                "birth_date": item.patient.birth_date,
                "sex": item.patient.sex,
                "study_instance_uid": item.study_instance_uid,
                "modality": item.modality,
                "station_ae_title": item.station_ae_title,
                "problem": item.problem,
            }
            for item in items
        ]
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return EXIT_OK
    if not items:
        print("未照合の撮影はありません")
        return EXIT_OK
    for item in items:
        patient = item.patient
        # MPPS はモダリティが送った値なので、端末に出す前に制御文字を見える形にする
        print(
            visible(
                "  ".join(
                    (
                        item.sop_instance_uid,
                        item.status,
                        item.modality,
                        patient.patient_id,
                        patient.name.to_dicom(),
                        item.study_instance_uid,
                        f"（照合できません：{item.problem}）" if item.problem else "",
                    )
                ).rstrip()
            )
        )
    return EXIT_OK


def reconcile_run_command(args: argparse.Namespace) -> int:
    service = _service(args)
    if args.roster_patient_id:
        if args.patient_id or args.name:
            raise ValidationError("--roster-patient-id と --patient-id・--name は同時に指定できません")
        patient = next(
            (p for p in service.roster_patients() if p.patient_id == args.roster_patient_id), None
        )
        if patient is None:
            raise ValidationError(f"名簿に無い患者ID です: {args.roster_patient_id}")
    elif args.patient_id and args.name:
        patient = _patient_from_args(args, service.config.orders)
    else:
        raise ValidationError("--roster-patient-id か、--patient-id と --name のどちらかが要ります")
    result = ReconciliationService(service).reconcile(
        ReconcileRequest(
            sop_instance_uid=args.sop_instance_uid,
            patient=patient,
            procedure_code=args.procedure,
            department=args.department,
        )
    )
    return _print_reconciliation(result, as_json=args.json)


def reconcile_resend_command(args: argparse.Namespace) -> int:
    result = ReconciliationService(_service(args)).send_pending(args.accession_number)
    return _print_reconciliation(result, as_json=args.json)


def _print_reconciliation(result: Reconciliation, *, as_json: bool) -> int:
    """照合の記録を出し、HL7 が受理されていなければ終了コード 5（拒否）・6（失敗）を返す."""
    if as_json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print(f"{result.accession_number}: 照合しました（MPPS {result.sop_instance_uid}）")
        for delivery in result.deliveries:
            reason = f"：{delivery.ack_code} {delivery.detail}".rstrip() if delivery.ack_code or delivery.detail else ""
            print(f"  {delivery.message_type}  {DELIVERY_LABELS[delivery.outcome]}{reason}")
    outcomes = {delivery.outcome for delivery in result.deliveries}
    if "rejected" in outcomes:
        return EXIT_HL7_REJECTED
    if "failed" in outcomes:
        return EXIT_HL7_FAILED
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
        print(f"[ERROR] {visible(str(exc))}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except (OrderNotFoundError, MppsNotFoundError, ReconciliationNotFoundError) as exc:
        print(f"[ERROR] {visible(str(exc))}", file=sys.stderr)
        return EXIT_NOT_FOUND
    except MwlServerError as exc:
        print(f"[ERROR] {visible(str(exc))}", file=sys.stderr)
        return EXIT_MWL_ERROR
