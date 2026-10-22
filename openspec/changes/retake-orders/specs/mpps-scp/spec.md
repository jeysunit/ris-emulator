# Spec Delta

## MODIFIED Requirements

### Requirement: 終わりの状態の予約は MPPS で変えない

結び付いた予約が終わりの状態（完了・取消・中止）か、MPPS が求める向きの遷移が `order-status` の
遷移の表に無いときは、予約の状態を変えずに MPPS の処理を成功にしなければならない（SHALL）。
MPPS はそのまま記録し、変えなかった予約と理由をログに出す。ただし `orders.retake_policy` が
`same_study` のときは、中止の予約に結び付く N-CREATE（IN PROGRESS）で、予約を実施中に戻す
（同じ予約の中の撮り直し）。

#### Scenario: 取消の予約の MPPS

- **WHEN** 取消の予約に一致する N-CREATE（IN PROGRESS）が届く
- **THEN** 応答の Status は 0000H になり、予約は取消のままになる

#### Scenario: same_study で中止の予約を撮り直す

- **WHEN** `same_study` の設定で、MPPS の DISCONTINUED で中止になった予約に、新しい MPPS の N-CREATE（IN PROGRESS）が届く
- **THEN** 応答の Status は 0000H になり、予約は実施中に戻り、その後の N-SET（COMPLETED）で完了になる

#### Scenario: new_order で中止の予約に MPPS が来る

- **WHEN** `new_order` の設定で、中止の予約に新しい MPPS の N-CREATE（IN PROGRESS）が届く
- **THEN** 応答の Status は 0000H になり、予約は中止のままになる
