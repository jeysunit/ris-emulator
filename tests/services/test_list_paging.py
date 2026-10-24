"""一覧のページと件数（OrderStore.list_orders の limit・offset と count_orders）."""

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
    # ページに切っても、並びは全件の並びと同じ
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


def test_query_and_counts_by_status(service: OrderService) -> None:
    first, second = service.create_orders(
        OrderRequest(counts={"CT": 2}, scheduled_date=TODAY, seed=1)
    )
    service.create_orders(OrderRequest(counts={"MR": 1}, scheduled_date=TODAY, seed=2))
    service.set_status(second.accession_number, OrderStatus.COMPLETED)
    for source in (service, service.store):
        assert source.list_orders(query=f" {first.patient.patient_id} ") == [first]
        assert source.count_orders(query=second.accession_number) == 1
        assert source.list_orders(query=first.accession_number[:-1]) == []
        assert source.count_orders(query="' OR 1=1 --") == 0
        assert source.count_orders(query="  ") == 3
        counts = source.count_orders_by_status(date_from="20261021", date_to="20261021", modality="CT")
        assert counts == {s: (1 if s in (OrderStatus.SCHEDULED, OrderStatus.COMPLETED) else 0) for s in OrderStatus}
        assert source.count_orders_by_status(query=first.patient.patient_id)[OrderStatus.SCHEDULED] == 1
        assert source.count_orders_by_status(date_to="20261020") == dict.fromkeys(OrderStatus, 0)
