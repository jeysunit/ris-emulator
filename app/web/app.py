"""Web 画面（FastAPI＋htmx。docs/spec/03_web_cli.md 3 章）."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date, timedelta
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
from app.services.config import AppConfig
from app.services.order_service import (
    MAX_INTERVAL_MINUTES,
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
        number = min(max(int(page) if page.isdigit() else 1, 1), pages)
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

    @app.get("/orders/new", response_class=HTMLResponse)
    def new_order_page(request: Request) -> HTMLResponse:
        return _render_form(request, error="", values={})

    def _render_form(
        request: Request, *, error: str, values: dict[str, Any], status_code: int = 200
    ) -> HTMLResponse:
        return render(
            request,
            "new_order.html",
            status_code=status_code,
            error=error,
            values=values,
            today=order_service.today(),
            catalog=config.orders.modalities,
            departments=config.orders.departments,
            character_sets=list(CharacterSet),
            character_set_labels=CHARACTER_SET_LABELS,
            default_character_set=config.orders.default_character_set,
            max_orders=MAX_ORDERS_PER_REQUEST,
            max_interval=MAX_INTERVAL_MINUTES,
        )

    @app.post("/orders")
    async def create_orders(request: Request) -> Response:
        form = await request.form()
        values = {key: value for key, value in form.items() if isinstance(value, str)}
        try:
            order_request = _order_request(values, config, order_service.today())
            orders = order_service.create_orders(order_request)
        except (ValidationError, ConfigurationError) as exc:
            return _render_form(
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
    first = parse_date_option(start_text.strip(), today)
    last = parse_date_option(end_text.strip(), today) if end_text.strip() else first
    if last < first:
        raise ValidationError("終了日は開始日と同じ日か、後の日にしてください")
    if (last - first).days + 1 > MAX_LIST_DAYS:
        raise ValidationError(f"予定日の期間は{MAX_LIST_DAYS}日までにしてください")
    return first, last


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


def _order_request(values: dict[str, str], config: AppConfig, today: date) -> OrderRequest:
    """画面のフォームの値を OrderRequest にする。誤りは ValidationError."""
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
    interval_text = values.get("interval", "15").strip() or "15"
    try:
        interval = int(interval_text)
    except ValueError as exc:
        raise ValidationError("間隔が数ではありません") from exc
    if not 0 <= interval <= MAX_INTERVAL_MINUTES:
        raise ValidationError(f"間隔は 0〜{MAX_INTERVAL_MINUTES} 分にしてください")
    seed_text = values.get("seed", "").strip()
    try:
        seed = int(seed_text) if seed_text else None
    except ValueError as exc:
        raise ValidationError("シードが数ではありません") from exc
    patients = values.get("patients", "random")
    if patients not in ("random", "roster"):
        raise ValidationError("患者は乱数か名簿を選んでください")
    charset = values.get("charset", "")
    try:
        character_set = CharacterSet(charset) if charset else None
    except ValueError as exc:
        raise ValidationError("文字コードを選び直してください") from exc
    return OrderRequest(
        counts=counts,
        scheduled_date=parse_date_option(values.get("date", "").strip(), today),
        start_time=parse_time_option(values.get("start", "09:00").strip() or "09:00"),
        interval_minutes=interval,
        patient_source=patients,  # type: ignore[arg-type]
        character_set=character_set,
        # 件数を入れたモダリティの装置だけを使う。空は「順に使う」
        stations={
            modality: name
            for modality in counts
            if (name := values.get(f"station_{modality}", "").strip())
        },
        department=values.get("department", "").strip() or None,
        seed=seed,
    )
