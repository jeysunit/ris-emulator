# Proposal

## Why

今は、モダリティで撮影を始めても終えても、予約の状態は変わらない。状態は画面と CLI で
手動で変更する（`docs/roadmap.md` の「次に作るもの」）。モダリティの MPPS
（Modality Performed Procedure Step）を受けて状態を進めると、撮影の開始・完了・中止が
RIS の画面と MWL に自動で反映され、モダリティの MPPS の送信も試験できる。

## What Changes

- MWL の SCP と同じ AE タイトル・ポートで、Modality Performed Procedure Step SOP Class
  （1.2.840.10008.3.1.2.3.3）の SCP を受け持つ（PS3.4 F.7）
- N-CREATE（Performed Procedure Step Status が `IN PROGRESS`）を受けたら、Scheduled Step
  Attributes Sequence の項目に一致する予約を「実施中」にする
- N-SET で Performed Procedure Step Status が `COMPLETED` になったら予約を「完了」、
  `DISCONTINUED` になったら「中止」にする
- 予約の状態に「中止」（`discontinued`）を足す。中止は終わりの状態で、MWL で返さない。
  手動では実施中からだけ中止にできる
- 予約に一致しない MPPS（予定の無い撮影）は、MPPS だけを記録して成功を返す
- 受けた MPPS（SOP Instance UID・状態・受けた属性・一致した予約）を、予約とは別の表に記録し、
  予約の詳細に表示する
- **BREAKING**（ADR-0001 の設計の要点からの変更）：ADR-0001 は DISCONTINUED を「取消」に
  するとしていたが、「中止」にする。取消は撮影を始める前の取り消しとして残す。ADR を
  新しく書き、ADR-0001 の「MPPS は次に作る」の節を置き換える

## Capabilities

### New Capabilities

- `mpps-scp`: MPPS の N-CREATE・N-SET を受ける SCP の動作、予約との結び付け、受けた MPPS の記録

### Modified Capabilities

- `order-status`: 状態に「中止」を足し、遷移の表・画面の選択肢・MWL で返す状態を変える
  （`order-status-transitions` を archive した後の spec に対する差分）

## Impact

- コード：`app/mwl/server.py`（MPPS の SOP Class と N-CREATE・N-SET の処理）、
  `app/core/models.py`（中止の状態と遷移）、`app/services/store.py`（MPPS の表と、状態の変更を
  1つのトランザクションで行う処理）、`app/services/config.py`（`mwl.statuses` の検証）、
  `app/web/templates/order_detail.html`
- データ：SQLite に MPPS の表を足す（起動のときに無ければ作る）。予約の表の形は変えない
- テスト：`tests/mwl/` に、pynetdicom の SCU から N-CREATE・N-SET を送る試験を足す
- ドキュメント：`docs/spec/` に MPPS の SCP の spec を足し、`01_orders.md` の 5 章、
  `02_mwl_scp.md` の 1 章、`docs/roadmap.md`、`docs/project_charter.md`、新しい ADR
- 前提：`order-status-transitions` を先に archive する
