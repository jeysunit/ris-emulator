"""予約の状態の遷移の表（docs/spec/01_orders.md 5 章）."""

from __future__ import annotations

import pytest

from app.core.models import OrderStatus, can_transition, is_final, selectable_statuses

S = OrderStatus.SCHEDULED
P = OrderStatus.IN_PROGRESS
C = OrderStatus.COMPLETED
X = OrderStatus.CANCELLED

# (今の状態, 変更後の状態) → 変更できるか。同じ状態は「何もしない」なので True
TABLE = {
    (S, S): True, (S, P): True, (S, C): True, (S, X): True,
    (P, S): True, (P, P): True, (P, C): True, (P, X): True,
    (C, S): False, (C, P): False, (C, C): True, (C, X): False,
    (X, S): False, (X, P): False, (X, C): False, (X, X): True,
}  # fmt: skip


def test_table_covers_every_pair() -> None:
    assert len(TABLE) == len(OrderStatus) ** 2


@pytest.mark.parametrize(("current", "new"), list(TABLE))
def test_can_transition(current: OrderStatus, new: OrderStatus) -> None:
    assert can_transition(current, new) is TABLE[(current, new)]


def test_final_states() -> None:
    assert [status for status in OrderStatus if is_final(status)] == [C, X]


def test_selectable_statuses() -> None:
    assert selectable_statuses(S) == [S, P, C, X]
    assert selectable_statuses(P) == [S, P, C, X]
    assert selectable_statuses(C) == [C]
    assert selectable_statuses(X) == [X]
