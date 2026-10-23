"""Web 画面（FastAPI＋htmx。docs/spec/03_web_cli.md 3 章）."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import __version__
from app.core.exceptions import (
    ConfigurationError,
    InvalidTransitionError,
    OrderNotFoundError,
    ValidationError,
)
from app.core.models import (
    CHARACTER_SET_LABELS,
    STATUS_LABELS,
    CharacterSet,
    Order,
    OrderStatus,
    is_final,
    selectable_statuses,
)
from app.core.mwl_dataset import order_to_dataset
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

from .auth import (
    CSRF_FIELD,
    basic_auth_ok,
    csrf_guard,
    host_header_is_loopback,
    is_loopback,
    new_csrf_token,
)

BASE_DIR = Path(__file__).resolve().parent
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_NOT_FOUND = 404
HTTP_SEE_OTHER = 303
# 一覧の1頁の件数と、予定日の期間の上限（docs/spec/03_web_cli.md 3.1）
LIST_PAGE_SIZE = 100
MAX_LIST_DAYS = 31
# 一括作成の間隔の既定（分）
DEFAULT_INTERVAL = 15
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
        context.update(
            csrf_token=app.state.csrf_token,
            csrf_field=CSRF_FIELD,
            mwl=mwl,
            mwl_config=config.mwl,
            status_labels=STATUS_LABELS,
            selectable_statuses=selectable_statuses,
            is_final=is_final,
            version=__version__,
        )
        return templates.TemplateResponse(request, name, context, status_code=status_code)

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
    ) -> HTMLResponse:
        modality = modality.upper()
        context: dict[str, Any] = {
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
        }
        total = order_service.count_orders(**where)
        pages = max(1, -(-total // LIST_PAGE_SIZE))
        number = min(max(_page_number(page), 1), pages)
        offset = (number - 1) * LIST_PAGE_SIZE
        orders = order_service.list_orders(**where, limit=LIST_PAGE_SIZE, offset=offset)

        def link(start: date, end: date, page_number: int = 1) -> str:
            query = {"date_from": start.isoformat(), "date_to": end.isoformat()}
            for key, value in (("status", status), ("modality", modality)):
                if value:
                    query[key] = value
            if page_number > 1:
                query["page"] = str(page_number)
            return f"/orders?{urlencode(query)}"

        context.update(
            date_from=first.isoformat(),
            date_to=last.isoformat(),
            orders=orders,
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
        request: Request, order: Order, *, error: str = "", status_code: int = 200
    ) -> HTMLResponse:
        return render(
            request,
            "order_detail.html",
            status_code=status_code,
            order=order,
            error=error,
            dataset=str(order_to_dataset(order)),
            character_set_labels=CHARACTER_SET_LABELS,
            mpps_records=order_service.list_mpps(order.accession_number),
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
        request: Request, accession_number: str, status: str = Form(...)
    ) -> Response:
        try:
            new_status = OrderStatus(status)
        except ValueError as exc:
            raise HTTPException(HTTP_BAD_REQUEST, "Unknown status") from exc
        try:
            order = order_service.set_status(accession_number, new_status)
        except OrderNotFoundError as exc:
            raise HTTPException(HTTP_NOT_FOUND, "Order not found") from exc
        except InvalidTransitionError as exc:
            # 一覧の行（htmx）は 4xx で置き換えない。詳細はエラーを付けて表示し直す
            if request.headers.get("hx-request"):
                raise HTTPException(HTTP_BAD_REQUEST, exc.message) from exc
            return _render_detail(
                request,
                _get_order(order_service, accession_number),
                error=f"{exc.message}。表示を読み直してください",
                status_code=HTTP_BAD_REQUEST,
            )
        if request.headers.get("hx-request"):
            return render(request, "_order_row.html", order=order)
        return RedirectResponse(f"/orders/{order.accession_number}", status_code=HTTP_SEE_OTHER)

    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    templates.env.filters["date_param"] = date_param
    templates.env.filters["hhmm"] = lambda value: f"{value[:2]}:{value[2:4]}" if value else ""
    templates.env.filters["ymd"] = (
        lambda value: f"{value[:4]}-{value[4:6]}-{value[6:]}" if len(value) == 8 else value
    )
    templates.env.filters["pn"] = lambda value: value.replace("^", " ")
    return app


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
    """頁の番号。ASCII の数字（6 桁まで）でなければ 1 頁目（範囲の外は呼ぶ側が最後の頁にする）."""
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
