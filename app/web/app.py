"""Web 画面（FastAPI＋htmx。docs/spec/03_web_cli.md 3 章）."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pydantic
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.core.exceptions import (
    AlreadyReconciledError,
    ConfigurationError,
    InvalidTransitionError,
    MppsNotFoundError,
    OrderNotFoundError,
    ReconciliationNotFoundError,
    ValidationError,
)
from app.core.models import (
    CHARACTER_SET_LABELS,
    STATUS_LABELS,
    CharacterSet,
    Order,
    OrderStatus,
    Patient,
    PersonName,
    can_transition,
    is_final,
    selectable_statuses,
)
from app.core.mwl_dataset import order_to_dataset
from app.core.patient_input import (
    INPUT_MESSAGES,
    PHONETIC_CONVERTED_NOTE,
    SCRIPT_LABELS,
    check_name_component,
    check_name_group,
    to_katakana,
    validate_birth_date,
    validate_patient_id_input,
    validate_sex,
)
from app.core.reconciliation import DELIVERY_LABELS
from app.mwl.server import MwlServer
from app.services.config import MINUTE_STEPS, AppConfig
from app.services.order_service import (
    MAX_ORDERS_PER_REQUEST,
    RETAKE_FROM,
    OrderRequest,
    OrderService,
    check_scheduled_date,
    parse_date_option,
    parse_time_option,
)
from app.services.reconciliation import (
    DEFAULT_DEPARTMENT,
    STATUS_MESSAGES,
    ReconcilePreview,
    ReconcileRequest,
    ReconciliationService,
)

from .auth import (
    CSRF_FIELD,
    basic_auth_ok,
    csrf_guard,
    host_header_is_loopback,
    is_loopback,
    new_csrf_token,
)
from .build_info import build_commit

BASE_DIR = Path(__file__).resolve().parent
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
HTTP_CONFLICT = 409
HTTP_SEE_OTHER = 303
# 一覧の1ページの件数と、予定日の期間の上限（docs/spec/03_web_cli.md 3.1）
LIST_PAGE_SIZE = 100
MAX_LIST_DAYS = 31
# 一括作成の間隔の既定（分）
DEFAULT_INTERVAL = 15
# MPPS の状態（PS3.4 F.7）→ 状態の札の種類と文字（予約の状態の札と同じ印と語）
MPPS_MARKS = {
    "IN PROGRESS": ("run", "実施中"),
    "COMPLETED": ("done", "完了"),
    "DISCONTINUED": ("stop", "中止"),
}
# 性別の DICOM・HL7 の値は画面に出さない（空と知らない値は空のまま）
SEX_LABELS = {"M": "男", "F": "女", "O": "その他", "U": "不明"}
# HL7 の送信の状態の札（ACK で断られたときも送信失敗。理由は詳細の列に出す）
DELIVERY_MARKS = {
    "pending": ("plan", "送信待ち"),
    "accepted": ("ok", "送信完了"),
    "rejected": ("ng", "送信失敗"),
    "failed": ("ng", "送信失敗"),
}
# 確認の窓で、送る HL7 の種類に添える言葉（docs/spec/07_reconciliation.md 4 章）
DELIVERY_PURPOSES = {
    "a40": "患者の統合",
    "a08": "患者の更新",
    "orm": "予約",
    "orm_ca": "予約の取消",
    "orm_dc": "予約の中止",
}
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cache-Control": "no-store",
}
BASIC_CHALLENGE = 'Basic realm="ris-emulator", charset="UTF-8"'


def create_app(
    config: AppConfig,
    *,
    password: str | None,
    service: OrderService | None = None,
    start_mwl: bool | None = None,
) -> FastAPI:
    """画面のアプリを作る。`password` があれば HTTP Basic を付ける.

    `start_mwl`（既定は設定の web.start_mwl）なら、起動のときに MWL の SCP も立てる。
    """
    order_service = service or OrderService(config)
    reconciliation_service = ReconciliationService(order_service)
    mwl = MwlServer(config.mwl, order_service.store)
    run_mwl = config.web.start_mwl if start_mwl is None else start_mwl

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if run_mwl:
            mwl.start()
        try:
            yield
        finally:
            mwl.stop()

    app = FastAPI(
        title="ris-emulator",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        dependencies=[Depends(csrf_guard)],
        lifespan=lifespan,
    )
    app.state.service = order_service
    app.state.mwl = mwl
    app.state.csrf_token = new_csrf_token()
    templates = Jinja2Templates(directory=BASE_DIR / "templates")
    check_host = is_loopback(config.web.bind_address)

    def render(request: Request, name: str, status_code: int = 200, **context: Any) -> HTMLResponse:
        context.setdefault(
            "nav_current",
            {
                "new_order.html": "new",
                "batch_order.html": "batch",
                "reconciliation_list.html": "reconciliation",
                "reconcile.html": "reconciliation",
                "version.html": "version",
            }.get(name, "orders"),
        )
        context.update(
            csrf_token=app.state.csrf_token,
            csrf_field=CSRF_FIELD,
            mwl=mwl,
            mwl_config=config.mwl,
            hl7_config=config.hl7,
            status_labels=STATUS_LABELS,
            selectable_statuses=selectable_statuses,
            is_final=is_final,
            version=__version__,
        )
        return templates.TemplateResponse(request, name, context, status_code=status_code)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        # フォームの送信を CSRF・origin の検査で断ったときは、何が起きてどうするかを画面で出す
        # （画面を開いた後にサーバーが起動し直すと、token が変わって断られる）。htmx は app.js が扱う
        if exc.status_code == HTTP_FORBIDDEN and not request.headers.get("hx-request"):
            return render(request, "rejected.html", status_code=HTTP_FORBIDDEN)
        return await http_exception_handler(request, exc)

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if check_host and not host_header_is_loopback(request.headers.get("host", "")):
            # ループバックで待ち受けるときの DNS rebinding よけ
            response: Response = PlainTextResponse("Invalid Host header", HTTP_BAD_REQUEST)
        elif password is not None and not basic_auth_ok(
            request.headers.get("authorization"), password
        ):
            response = PlainTextResponse(
                "Authentication required",
                HTTP_UNAUTHORIZED,
                headers={"WWW-Authenticate": BASIC_CHALLENGE},
            )
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse("/orders", status_code=HTTP_SEE_OTHER)

    @app.get("/orders", response_class=HTMLResponse)
    def orders_page(
        request: Request,
        date_from: str = "",
        date_to: str = "",
        date: str = "",
        status: str = "",
        modality: str = "",
        page: str = "1",
        q: str = "",
        selected: str = "",
    ) -> HTMLResponse:
        q = q.strip()
        modality = modality.upper()
        context: dict[str, Any] = {
            "q": q,
            "summary": [],
            "status": status,
            "modality": modality,
            "modalities": list(config.orders.modalities),
            "statuses": list(OrderStatus),
            "date_from": date_from or date,
            "date_to": date_to,
        }
        try:
            first, last = _list_period(date_from or date, date_to, order_service.today())
        except ValidationError as exc:
            return render(
                request, "orders.html", status_code=HTTP_BAD_REQUEST, error=exc.message, **context
            )
        statuses = [OrderStatus(status)] if status in {s.value for s in OrderStatus} else None
        where = {
            "date_from": first.strftime("%Y%m%d"),
            "date_to": last.strftime("%Y%m%d"),
            "statuses": statuses,
            "modality": modality,
            "query": q,
        }
        total = order_service.count_orders(**where)
        pages = max(1, -(-total // LIST_PAGE_SIZE))
        number = min(max(_page_number(page), 1), pages)
        offset = (number - 1) * LIST_PAGE_SIZE
        orders = order_service.list_orders(**where, limit=LIST_PAGE_SIZE, offset=offset)

        def link(
            start: date, end: date, page_number: int = 1,
            chosen_status: str = status, selection: str = "",
        ) -> str:
            query = {"date_from": start.isoformat(), "date_to": end.isoformat()}
            for key, value in (
                ("status", chosen_status), ("modality", modality), ("q", q), ("selected", selection)
            ):
                if value:
                    query[key] = value
            if page_number > 1:
                query["page"] = str(page_number)
            return f"/orders?{urlencode(query)}"

        counts = order_service.count_orders_by_status(
            date_from=where["date_from"], date_to=where["date_to"], modality=modality, query=q
        )
        chosen = next(
            (o for o in orders if o.accession_number == selected), orders[0] if orders else None
        )
        context.update(
            date_from=first.isoformat(),
            date_to=last.isoformat(),
            orders=orders,
            selected_order=chosen,
            status_confirm=_status_confirm(
                chosen is not None
                and reconciliation_service.get_reconciliation(chosen.accession_number) is not None,
                config,
            ),
            status_hx=True,
            selection_links={
                o.accession_number: link(first, last, number, selection=o.accession_number)
                for o in orders
            },
            summary=[("", "すべて", sum(counts.values()), link(first, last, chosen_status=""))]
            + [
                (s.value, STATUS_LABELS[s], counts[s], link(first, last, chosen_status=s.value))
                for s in OrderStatus
            ],
            period_label=first.strftime("%Y/%m/%d")
            + ("〜" + last.strftime("%Y/%m/%d") if first != last else ""),
            today=order_service.today(),
            can_retake=chosen is not None
            and config.orders.retake_mode == "new_order" and chosen.status in RETAKE_FROM,
            total=total,
            first_index=offset + 1,
            last_index=offset + len(orders),
            prev_page=link(first, last, number - 1) if number > 1 else "",
            next_page=link(first, last, number + 1) if number < pages else "",
            prev_day=_shifted_link(link, first, last, -1),
            next_day=_shifted_link(link, first, last, 1),
        )
        return render(request, "orders.html", error="", **context)

    def _form_context() -> dict[str, Any]:
        """予約作成と一括作成の画面に共通の選択肢."""
        return {
            "today": order_service.today(),
            "catalog": config.orders.modalities,
            "departments": config.orders.departments,
            "character_sets": list(CharacterSet),
            "character_set_labels": CHARACTER_SET_LABELS,
            "default_character_set": config.orders.default_character_set,
            "hours": [f"{hour:02d}" for hour in range(24)],
        }

    @app.get("/orders/new", response_class=HTMLResponse)
    def new_order_page(request: Request) -> HTMLResponse:
        return _render_entry(request, error="", values={})

    def _render_entry(
        request: Request, *, error: str, values: dict[str, Any], status_code: int = 200
    ) -> HTMLResponse:
        try:
            roster = order_service.roster_patients()
            roster_error = ""
        except ConfigurationError as exc:
            roster, roster_error = [], f"名簿を読めません（{exc.message}）"
        modality = values.get("modality", "")
        if modality not in config.orders.modalities:
            modality = next(iter(config.orders.modalities))
        return render(
            request,
            "new_order.html",
            status_code=status_code,
            error=error,
            values=values,
            roster=roster,
            roster_error=roster_error,
            modality=modality,
            entry=config.orders.modalities[modality],
            minutes=_minutes(config.orders.slot_minutes),
            **_form_context(),
        )

    @app.get("/orders/new/exam", response_class=HTMLResponse)
    def entry_exam_options(request: Request, modality: str = "") -> HTMLResponse:
        """モダリティを変えたときの、検査名と装置の選択肢（htmx）."""
        if modality not in config.orders.modalities:
            raise HTTPException(HTTP_BAD_REQUEST, "Unknown modality")
        return render(
            request, "_exam_options.html", entry=config.orders.modalities[modality], values={}
        )

    @app.post("/orders")
    async def create_order(request: Request) -> Response:
        form = await request.form()
        values = {key: value for key, value in form.items() if isinstance(value, str)}
        try:
            order_request = _entry_request(values, config, order_service.today())
            order = order_service.create_orders(order_request)[0]
        except (ValidationError, ConfigurationError) as exc:
            return _render_entry(
                request, error=exc.message, values=values, status_code=HTTP_BAD_REQUEST
            )
        return RedirectResponse(f"/orders/{order.accession_number}", status_code=HTTP_SEE_OTHER)

    @app.get("/orders/batch", response_class=HTMLResponse)
    def batch_page(request: Request) -> HTMLResponse:
        return _render_batch(request, error="", values={})

    def _render_batch(
        request: Request, *, error: str, values: dict[str, Any], status_code: int = 200
    ) -> HTMLResponse:
        interval = _choice(values.get("interval", ""), MINUTE_STEPS, DEFAULT_INTERVAL)
        return render(
            request,
            "batch_order.html",
            status_code=status_code,
            error=error,
            values=values,
            max_orders=MAX_ORDERS_PER_REQUEST,
            intervals=MINUTE_STEPS,
            interval=interval,
            minutes=_minutes(interval),
            **_form_context(),
        )

    @app.get("/orders/batch/minutes", response_class=HTMLResponse)
    def batch_minutes(request: Request, interval: str = "", minute: str = "") -> HTMLResponse:
        """間隔を変えたときの、開始時刻の分の選択肢（htmx）。今の分が新しい間隔に合えば残す."""
        step = _choice(interval, MINUTE_STEPS, DEFAULT_INTERVAL)
        return render(request, "_minute_select.html", minutes=_minutes(step), selected=minute)

    @app.post("/orders/batch")
    async def create_batch(request: Request) -> Response:
        form = await request.form()
        values = {key: value for key, value in form.items() if isinstance(value, str)}
        try:
            order_request = _batch_request(values, config, order_service.today())
            orders = order_service.create_orders(order_request)
        except (ValidationError, ConfigurationError) as exc:
            return _render_batch(
                request, error=exc.message, values=values, status_code=HTTP_BAD_REQUEST
            )
        day = date_param(orders[0].scheduled_date) if orders else ""
        return RedirectResponse(f"/orders?date_from={day}", status_code=HTTP_SEE_OTHER)

    @app.get("/orders/{accession_number}", response_class=HTMLResponse)
    def order_detail(request: Request, accession_number: str) -> HTMLResponse:
        return _render_detail(request, _get_order(order_service, accession_number))

    def _render_detail(
        request: Request,
        order: Order,
        *,
        error: str = "",
        status_code: int = 200,
        confirm_status: OrderStatus | None = None,
    ) -> HTMLResponse:
        reconciliation = reconciliation_service.get_reconciliation(order.accession_number)
        before = reconciliation.temporary if reconciliation else {}
        return render(
            request,
            "order_detail.html",
            status_code=status_code,
            confirm_status=confirm_status,
            status_confirm=_status_confirm(reconciliation is not None, config),
            status_hx=False,
            order=order,
            temporary_name=PersonName(
                alphabetic=before.get("alphabetic", ""),
                ideographic=before.get("ideographic", ""),
                phonetic=before.get("phonetic", ""),
            ).to_dicom(),
            error=error,
            dataset=str(order_to_dataset(order)),
            character_set_labels=CHARACTER_SET_LABELS,
            mpps_records=order_service.list_mpps(order.accession_number),
            reconciliation=reconciliation,
            delivery_labels=DELIVERY_LABELS,
            retakes=order_service.list_retakes(order.accession_number),
            can_retake=config.orders.retake_mode == "new_order" and order.status in RETAKE_FROM,
            today=order_service.today(),
        )

    @app.post("/orders/{accession_number}/retake")
    async def create_retake(request: Request, accession_number: str) -> Response:
        form = await request.form()
        values = {key: value for key, value in form.items() if isinstance(value, str)}
        today = order_service.today()
        try:
            date_text = values.get("date", "").strip()
            start_text = values.get("start", "").strip()
            retake, _ = order_service.create_retake(
                accession_number,
                scheduled_date=parse_date_option(date_text, today) if date_text else None,
                start_time=parse_time_option(start_text) if start_text else None,
            )
        except OrderNotFoundError as exc:
            raise HTTPException(HTTP_NOT_FOUND, "Order not found") from exc
        except ValidationError as exc:
            return _render_detail(
                request,
                _get_order(order_service, accession_number),
                error=exc.message,
                status_code=HTTP_BAD_REQUEST,
            )
        return RedirectResponse(f"/orders/{retake.accession_number}", status_code=HTTP_SEE_OTHER)

    @app.post("/orders/{accession_number}/status")
    def change_status(
        request: Request, accession_number: str, status: str = Form(...), confirmed: str = Form("")
    ) -> Response:
        try:
            new_status = OrderStatus(status)
        except ValueError as exc:
            raise HTTPException(HTTP_BAD_REQUEST, "Unknown status") from exc
        current = _get_order(order_service, accession_number)
        if (
            is_final(new_status)
            and confirmed != "1"
            and new_status != current.status
            and can_transition(current.status, new_status)
        ):
            # 終わりの状態へは、確認の窓の実行（confirmed=1）でだけ変える。窓を通らない送信は、
            # 画面なら窓を開いた詳細を出し、htmx なら断る（app.js が窓を開いてから送る）
            if request.headers.get("hx-request"):
                raise HTTPException(HTTP_BAD_REQUEST, "Confirmation required")
            return _render_detail(request, current, confirm_status=new_status)
        try:
            order, _ = reconciliation_service.set_status(accession_number, new_status)
        except OrderNotFoundError as exc:
            raise HTTPException(HTTP_NOT_FOUND, "Order not found") from exc
        except InvalidTransitionError as exc:
            # 選んだ予約の区画（htmx）は 4xx で置き換えない。詳細はエラーを付けて表示し直す
            if request.headers.get("hx-request"):
                raise HTTPException(HTTP_BAD_REQUEST, exc.message) from exc
            return _render_detail(
                request,
                _get_order(order_service, accession_number),
                error=f"{exc.message}。表示を読み直してください",
                status_code=HTTP_BAD_REQUEST,
            )
        if request.headers.get("hx-request"):
            return Response(status_code=204, headers={"HX-Refresh": "true"})
        return RedirectResponse(f"/orders/{order.accession_number}", status_code=HTTP_SEE_OTHER)

    @app.get("/version", response_class=HTMLResponse)
    def version_page(request: Request) -> HTMLResponse:
        return render(request, "version.html", build_commit=build_commit())

    @app.get("/reconciliation", response_class=HTMLResponse)
    def reconciliation_list(request: Request) -> HTMLResponse:
        return render(
            request, "reconciliation_list.html", items=reconciliation_service.list_unreconciled()
        )

    @app.get("/reconciliation/{sop_instance_uid}", response_class=HTMLResponse)
    def reconciliation_form(request: Request, sop_instance_uid: str) -> HTMLResponse:
        return _render_reconcile(request, sop_instance_uid, error="", values={})

    def _render_reconcile(
        request: Request,
        sop_instance_uid: str,
        *,
        error: str,
        values: dict[str, Any],
        status_code: int = 200,
        confirm: dict[str, Any] | None = None,
    ) -> HTMLResponse:
        try:
            item, linked = reconciliation_service.get_mpps(sop_instance_uid)
        except MppsNotFoundError as exc:
            raise HTTPException(HTTP_NOT_FOUND, "MPPS not found") from exc
        try:
            roster = order_service.roster_patients()
            roster_error = ""
        except ConfigurationError as exc:
            roster, roster_error = [], f"名簿を読めません（{exc.message}）"
        return render(
            request,
            "reconcile.html",
            status_code=status_code,
            confirm=confirm,
            error=error,
            values=values,
            item=item,
            linked=linked[0] if linked else "",
            roster=roster,
            roster_error=roster_error,
            procedures=reconciliation_service.procedures_for(item.modality),
            departments=config.orders.departments,
            default_department=DEFAULT_DEPARTMENT,
            input_messages=INPUT_MESSAGES,
            phonetic_converted_note=PHONETIC_CONVERTED_NOTE,
            charset_is_jis=config.orders.default_character_set != CharacterSet.UTF8,
            test_mode=config.orders.patient_input_test_mode,
        )

    @app.post("/reconciliation/{sop_instance_uid}")
    async def reconcile(request: Request, sop_instance_uid: str) -> Response:
        form = await request.form()
        values = {key: value for key, value in form.items() if isinstance(value, str)}
        try:
            patient = _reconcile_patient(values, order_service)
            department = values.get("department", "").strip()
            if department and department not in config.orders.departments:
                raise ValidationError("依頼科を選び直してください")
            reconcile_request = ReconcileRequest(
                sop_instance_uid=sop_instance_uid,
                patient=patient,
                procedure_code=values.get("procedure", "").strip() or None,
                department=department or None,
            )
            preview = reconciliation_service.preview(reconcile_request)
            known = reconciliation_service.known_patients(patient.patient_id)
            if values.get("patient") == "manual":
                _refuse_another_patient(patient, known)
            key = values.get("confirmed_key", "")
            if not key or key != preview.key:
                # 確認の窓（照合の内容と送る HL7）を出す。窓の「照合・送信する」で鍵を付けて送り直す。
                # 鍵が違えば、確かめた後に内容が変わったので、窓を出し直す
                return _render_reconcile(
                    request,
                    sop_instance_uid,
                    error="確かめた後に内容が変わりました。もう一度確かめてください" if key else "",
                    values=values,
                    confirm=_reconcile_confirm(preview, patient, known, config),
                )
            result = reconciliation_service.reconcile(
                replace(reconcile_request, confirmed_key=key)
            )
        except MppsNotFoundError as exc:
            raise HTTPException(HTTP_NOT_FOUND, "MPPS not found") from exc
        except AlreadyReconciledError as exc:
            return _render_reconcile(
                request, sop_instance_uid, error=exc.message, values=values, status_code=HTTP_CONFLICT
            )
        except (ValidationError, ConfigurationError) as exc:
            return _render_reconcile(
                request,
                sop_instance_uid,
                error=exc.message,
                values=values,
                status_code=HTTP_BAD_REQUEST,
            )
        return RedirectResponse(f"/orders/{result.accession_number}", status_code=HTTP_SEE_OTHER)

    @app.post("/orders/{accession_number}/hl7/resend")
    def resend_hl7(accession_number: str) -> Response:
        try:
            reconciliation_service.send_pending(accession_number)
        except ReconciliationNotFoundError as exc:
            raise HTTPException(HTTP_NOT_FOUND, "Reconciliation not found") from exc
        return RedirectResponse(f"/orders/{accession_number}", status_code=HTTP_SEE_OTHER)

    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    templates.env.filters["date_param"] = date_param
    templates.env.filters["hhmm"] = lambda value: f"{value[:2]}:{value[2:4]}" if value else ""
    templates.env.filters["ymd"] = ymd
    templates.env.filters["md"] = lambda value: f"{value[4:6]}/{value[6:]}" if len(value) == 8 else value
    templates.env.filters["pn"] = lambda value: value.replace("^", " ")
    templates.env.filters["sex"] = lambda value: SEX_LABELS.get(value, "")
    templates.env.filters["when"] = when
    templates.env.filters["birth"] = lambda value: birth(value, order_service.today())
    templates.env.globals["mpps_marks"] = MPPS_MARKS
    templates.env.globals["delivery_marks"] = DELIVERY_MARKS
    return app


def ymd(value: str) -> str:
    """画面の日付：DICOM の DA（YYYYMMDD）→ yyyy/MM/dd。形の合わない値はそのまま."""
    return f"{value[:4]}/{value[4:6]}/{value[6:]}" if len(value) == 8 and value.isdigit() else value


def when(value: str) -> str:
    """画面の日時：記録の ISO 8601（秒・時差つき）→ yyyy/MM/dd HH:mm（その時差のまま）。読めない値はそのまま."""
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    return moment.strftime("%Y/%m/%d %H:%M")


def birth(value: str, today: date) -> str:
    """生年月日と年齢：19700401 → 1970/04/01（56 歳）。日付として読めなければ ymd と同じ."""
    try:
        born = datetime.strptime(value, "%Y%m%d").date()
    except (TypeError, ValueError):
        return ymd(value)
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return f"{ymd(value)}（{age} 歳）" if age >= 0 else ymd(value)


def date_param(value: str | date) -> str:
    """URL の日付（YYYY-MM-DD）."""
    if isinstance(value, date):
        return value.isoformat()
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def _list_period(start_text: str, end_text: str, today: date) -> tuple[date, date]:
    """一覧の予定日の期間（両端を含む）。開始日が空なら本日、終了日が空なら開始日の1日."""
    if start_text == "all" or end_text == "all":
        raise ValidationError(f"予定日は開始日と終了日で指定してください（{MAX_LIST_DAYS}日まで）")
    try:
        first = parse_date_option(start_text.strip(), today)
        last = parse_date_option(end_text.strip(), today) if end_text.strip() else first
    except ValidationError as exc:
        # parse_date_option の文は CLI の書き方（today・tomorrow）なので、画面の書き方で言い直す
        raise ValidationError("予定日は YYYY-MM-DD の日付で指定してください") from exc
    if last < first:
        raise ValidationError("終了日は開始日と同じ日か、後の日にしてください")
    if (last - first).days + 1 > MAX_LIST_DAYS:
        raise ValidationError(f"予定日の期間は{MAX_LIST_DAYS}日までにしてください")
    return first, last


def _page_number(text: str) -> int:
    """ページの番号。ASCII の数字（6 桁まで）でなければ 1 ページ目（範囲の外は呼ぶ側が最後のページにする）."""
    return int(text) if re.fullmatch(r"[0-9]{1,6}", text) else 1


def _shifted_link(
    link: Callable[[date, date], str], first: date, last: date, days: int
) -> str:
    """期間を `days` 日動かした一覧の URL。予定日の範囲（1900〜9999 年）を出るなら空."""
    try:
        start = check_scheduled_date(first + timedelta(days=days))
        end = check_scheduled_date(last + timedelta(days=days))
    except (OverflowError, ValidationError):
        return ""
    return link(start, end)


def _get_order(service: OrderService, accession_number: str):  # noqa: ANN202
    try:
        return service.get(accession_number)
    except OrderNotFoundError as exc:
        raise HTTPException(HTTP_NOT_FOUND, "Order not found") from exc


def _minutes(step: int) -> list[str]:
    """分の選択肢（00 から `step` 分ごと）."""
    return [f"{minute:02d}" for minute in range(0, 60, step)]


def _choice(text: str, choices: tuple[int, ...], default: int) -> int:
    """選択肢の数（`text` が選択肢に無ければ既定値）."""
    return int(text) if text.isascii() and text.isdigit() and int(text) in choices else default


def _form_date(values: dict[str, str], today: date) -> date:
    try:
        return parse_date_option(values.get("date", "").strip(), today)
    except ValidationError as exc:
        # parse_date_option の文は CLI の書き方（today・tomorrow）なので、画面の書き方で言い直す
        raise ValidationError("予定日は YYYY-MM-DD の日付で指定してください") from exc


def _form_time(values: dict[str, str], step: int, label: str) -> time:
    """時と分の選択肢の値を時刻にする。分は `step` 分ごとだけを受ける."""
    hour, minute = values.get("hour", "").strip(), values.get("minute", "").strip()
    if not (re.fullmatch(r"[0-9]{2}", hour) and re.fullmatch(r"[0-9]{2}", minute)):
        raise ValidationError(f"{label}の時と分を選んでください")
    if int(hour) > 23 or int(minute) > 59:  # noqa: PLR2004 - 時刻の範囲
        raise ValidationError(f"{label}の時と分を選び直してください")
    if int(minute) % step:
        raise ValidationError(f"{label}の分は {step} 分ごとにしてください")
    return time(int(hour), int(minute))


def _form_character_set(values: dict[str, str]) -> CharacterSet | None:
    charset = values.get("charset", "")
    try:
        return CharacterSet(charset) if charset else None
    except ValueError as exc:
        raise ValidationError("文字コードを選び直してください") from exc


def _reconcile_patient(values: dict[str, str], service: OrderService) -> Patient:
    """照合のフォームの正式な患者。名簿から選ぶか、入力する。誤りは ValidationError."""
    source = values.get("patient", "")
    if source == "roster":
        patient_id = values.get("roster_patient_id", "").strip()
        if not patient_id:
            raise ValidationError("名簿の患者を選んでください")
        patient = next((p for p in service.roster_patients() if p.patient_id == patient_id), None)
        if patient is None:
            raise ValidationError(f"名簿に無い患者ID です: {patient_id}")
        return patient
    if source != "manual":
        raise ValidationError("患者を、名簿から選ぶか入力するかを選んでください")
    patient_id = values.get("patient_id", "").strip()
    validate_patient_id_input(patient_id)
    groups = {}
    for script, label in SCRIPT_LABELS.items():
        family = values.get(f"{script}_family", "").strip()
        given = values.get(f"{script}_given", "").strip()
        for part in (family, given):
            message = check_name_component(label, part)
            if message:
                raise ValidationError(message)
        groups[script] = f"{family}^{given}".rstrip("^") if family or given else ""
    if not any(groups.values()):
        raise ValidationError("氏名を入力してください")
    orders = service.config.orders
    if not orders.patient_input_test_mode:
        groups["phonetic"] = to_katakana(groups["phonetic"])
    for script, label in SCRIPT_LABELS.items():
        message = check_name_group(
            script,
            label,
            groups[script],
            orders.default_character_set,
            test_mode=orders.patient_input_test_mode,
        )
        if message:
            raise ValidationError(message)
    birth_date = values.get("birth_date", "").strip().replace("-", "")
    sex = values.get("sex", "").strip()
    # pydantic の英語の文より先に、日本語の文で断る
    validate_birth_date(birth_date)
    validate_sex(sex)
    try:
        patient = Patient(
            patient_id=patient_id,
            name=PersonName(**groups),
            birth_date=birth_date,
            sex=sex,
        )
    except pydantic.ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        raise ValidationError(f"患者の値を受け付けられません: {location}: {first['msg']}") from exc
    return patient


def _status_confirm(reconciled: bool, config: AppConfig) -> dict[str, Any]:
    """状態の確認の窓に出す、送る HL7（照合で作った予約の取消・中止だけ）と送り先."""
    hl7 = config.hl7
    sends = {
        status.value: (message_type, DELIVERY_PURPOSES[kind])
        for status, (kind, message_type) in STATUS_MESSAGES.items()
    }
    return {
        "sends": sends if reconciled else {},
        "destination": f"{hl7.receiving_application}（{hl7.host}:{hl7.port}）",
    }


def _person(patient: Any) -> str:  # noqa: ANN401 - Patient と照合前の患者（TemporaryPatient）
    """確認の窓と誤りの文で患者を見分ける名前（漢字 → 英字 → かなの順で、値のある表記）."""
    name = patient.name
    return (name.ideographic or name.alphabetic or name.phonetic).replace("^", " ")


def _refuse_another_patient(patient: Patient, known: list[Patient]) -> None:
    """手で入れた患者ID が既にある患者のもので、氏名・生年月日・性別が合わなければ断る."""
    other = ReconciliationService.another_patient(patient, known)
    if other is not None:
        facts = " ".join(v for v in (_person(other), ymd(other.birth_date), SEX_LABELS.get(other.sex, "")) if v)
        raise ValidationError(
            f"患者ID {patient.patient_id} は、既にある患者（{facts}）の患者ID です。"
            "入力した氏名・生年月日・性別と合いません。名簿から選ぶか、患者ID を確かめてください"
        )


def _reconcile_confirm(
    preview: ReconcilePreview, patient: Patient, known: list[Patient], config: AppConfig
) -> dict[str, Any]:
    """照合の確認の窓に出す内容：仮の患者と正式な患者を並べた表、送る HL7 と送り先."""
    temporary = preview.unreconciled.patient
    # 手で入れた患者ID が既にある患者のものなら、その患者も並べる（名簿から選んだ患者は同じ値）
    existing = next((p for p in known if p != patient), None)
    fields: list[tuple[str, Callable[[Any], str]]] = [
        ("患者ID", lambda p: p.patient_id),
        ("氏名（漢字）", lambda p: p.name.ideographic.replace("^", " ")),
        ("氏名（かな）", lambda p: p.name.phonetic.replace("^", " ")),
        ("氏名（英字）", lambda p: p.name.alphabetic.replace("^", " ")),
        ("生年月日", lambda p: ymd(p.birth_date)),
        ("性別", lambda p: SEX_LABELS.get(p.sex, "")),
    ]
    rows = [
        {
            "label": label,
            "before": pick(temporary),
            "after": pick(patient),
            "other": pick(existing) if existing else "",
        }
        for label, pick in fields
    ]
    hl7 = config.hl7
    return {
        "title": f"{_person(temporary)}（{temporary.patient_id}）を "
        f"{_person(patient)}（{patient.patient_id}）に照合しますか？",
        "rows": rows,
        "existing": existing is not None,
        "accession_number": preview.unreconciled.accession_number,
        "messages": [
            (message_type, DELIVERY_PURPOSES[kind])
            for message_type, kind in zip(preview.message_types, preview.deliveries, strict=True)
        ],
        "merges": "a40" in preview.deliveries,
        "destination": f"{hl7.receiving_application}（{hl7.host}:{hl7.port}）",
        "procedure": preview.procedure,
        "department": preview.department,
        "key": preview.key,
    }


def _entry_request(values: dict[str, str], config: AppConfig, today: date) -> OrderRequest:
    """予約作成（1件）のフォームの値を OrderRequest にする。誤りは ValidationError."""
    patient = values.get("patient", "")
    roster_patient_id = values.get("roster_patient_id", "").strip()
    if patient == "roster":
        if not roster_patient_id:
            raise ValidationError("名簿の患者を選んでください")
    elif patient != "new":
        raise ValidationError("患者を、名簿から選ぶか新規にするかを選んでください")
    modality = values.get("modality", "")
    if modality not in config.orders.modalities:
        raise ValidationError("モダリティを選び直してください")
    procedure = values.get("procedure", "").strip()
    if not procedure:
        raise ValidationError("検査名を選んでください")
    station = values.get("station", "").strip()
    if not station:
        raise ValidationError("装置を選んでください")
    department = values.get("department", "").strip()
    if department not in config.orders.departments:
        raise ValidationError("依頼科を選んでください")
    return OrderRequest(
        counts={modality: 1},
        scheduled_date=_form_date(values, today),
        start_time=_form_time(values, config.orders.slot_minutes, "予定時刻"),
        interval_minutes=0,
        patient_source="roster" if patient == "roster" else "random",
        roster_patient_id=roster_patient_id if patient == "roster" else None,
        procedure_code=procedure,
        character_set=_form_character_set(values),
        stations={modality: station},
        department=department,
    )


def _batch_request(values: dict[str, str], config: AppConfig, today: date) -> OrderRequest:
    """一括作成のフォームの値を OrderRequest にする。誤りは ValidationError."""
    counts: dict[str, int] = {}
    for modality in config.orders.modalities:
        text = values.get(f"count_{modality}", "").strip()
        if not text:
            continue
        try:
            count = int(text)
        except ValueError as exc:
            raise ValidationError(f"{modality} の件数が数ではありません") from exc
        if count < 0:
            raise ValidationError(f"{modality} の件数は 0 以上にしてください")
        if count:
            counts[modality] = count
    if not counts:
        raise ValidationError("どれかのモダリティに 1 以上の件数を入れてください")
    interval_text = values.get("interval", "").strip()
    if not (interval_text.isascii() and interval_text.isdigit() and int(interval_text) in MINUTE_STEPS):
        raise ValidationError(f"間隔は {'・'.join(map(str, MINUTE_STEPS))} 分から選んでください")
    interval = int(interval_text)
    patients = values.get("patients", "random")
    if patients not in ("random", "roster"):
        raise ValidationError("患者は新規（架空）か名簿から無作為にを選んでください")
    return OrderRequest(
        counts=counts,
        scheduled_date=_form_date(values, today),
        start_time=_form_time(values, interval, "開始時刻"),
        interval_minutes=interval,
        patient_source=patients,  # type: ignore[arg-type]
        character_set=_form_character_set(values),
        # 件数を入れたモダリティの装置だけを使う。空は「全装置に振り分け」
        stations={
            modality: name
            for modality in counts
            if (name := values.get(f"station_{modality}", "").strip())
        },
        department=values.get("department", "").strip() or None,
    )
