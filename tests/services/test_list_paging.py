"""一覧の頁と件数（OrderStore.list_orders の limit・offset と count_orders）."""

from __future__ import annotations

from datetime import timedelta

from app.core.models import OrderStatus
from app.services.order_service import OrderRequest, OrderService
from tests.conftest import TODAY


def test_limit_offset_and_count(service: OrderService) -> None:
    service.create_orders(
        OrderRequest(counts={"CT": 5, "MR": 2}, scheduled_date=TODAY, interval_minutes=1, seed=1)
    )
    service.create_orders(
        OrderRequest(counts={"CT": 1}, scheduled_date=TODAY + timedelta(days=1), seed=2)
    )
    everything = service.list_orders()
    assert service.count_orders() == len(everything) == 8
    # 頁に切っても、並びは全件の並びと同じ
    pages = [service.list_orders(limit=3, offset=offset) for offset in (0, 3, 6)]
    assert [len(page) for page in pages] == [3, 3, 2]
    assert [o.accession_number for page in pages for o in page] == [
        o.accession_number for o in everything
    ]
    assert service.list_orders(limit=3, offset=9) == []
    today = TODAY.strftime("%Y%m%d")
    assert service.count_orders(date_from=today, date_to=today) == 7
    assert service.count_orders(modality="MR") == 2
    assert service.count_orders(statuses=[OrderStatus.COMPLETED]) == 0
