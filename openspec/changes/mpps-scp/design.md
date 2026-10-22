# Design

## Context

- MWL の SCP（`app/mwl/server.py` の `MwlServer`）は pynetdicom の `AE` を1つ立て、C-FIND と
  C-ECHO を受ける。画面のプロセスの中で別のスレッドとして動く
- 予約は SQLite（`OrderStore`）にあり、状態の変更は `BEGIN IMMEDIATE` のトランザクションで行う。
  `order-status-transitions` で、遷移の表（`ALLOWED_TRANSITIONS`）と検証がストアに入る
- ADR-0001 の「MPPS は次に作る」の節に、設計の要点（同じ `MwlServer` に足す、Accession Number と
  Scheduled Procedure Step ID で探す、MPPS は別の表に記録する、受けた値を信用しない）がある。
  DISCONTINUED を「取消」にする点だけを、この change で「中止」に変える
- 規格の出典（DICOM 2026d、2026-10-23 に確認）
  - PS3.4 F.7.2.1（N-CREATE。SCP は `IN PROGRESS` 以外を 0106H で断る）
  - PS3.4 F.7.2.2.2・F.7.2.2.3（N-SET。`COMPLETED`・`DISCONTINUED` の後は SCU は変更しない。
    SCP は `IN PROGRESS` でない MPPS への N-SET を 0110H で断る）、Table F.7.2-2（Error ID A710）
  - PS3.4 Table F.7.2-1（Scheduled Step Attributes Sequence (0040,0270) は N-CREATE で 1/1、
    その中の Accession Number と Scheduled Procedure Step ID は 2/2、N-SET では Not allowed）
  - PS3.3 C.4.14（Performed Procedure Step Status の Enumerated Values：IN PROGRESS・
    DISCONTINUED・COMPLETED）
  - PS3.7 C.5.8（0111H Duplicate SOP Instance）・C.5.11（0106H Invalid Attribute Value）・
    C.5.19（0112H No such SOP Instance）・C.5.21（0110H Processing Failure）
  - HL7 v2 Table 0038 Order Status（IP・CM・DC・CA）、IHE RAD の Scheduled Workflow の
    RAD-6（Modality Procedure Step In Progress）・RAD-7（Modality Procedure Step Completed）

## Goals / Non-Goals

**Goals:**

- モダリティの MPPS の N-CREATE・N-SET を PS3.4 F.7 のとおりに受け、予約の状態に反映する
- 受けた MPPS を、予約と別に記録して後から確かめられるようにする

**Non-Goals:**

- MPPS の N-GET・N-EVENT-REPORT（Modality Performed Procedure Step Retrieve・Notification の
  SOP Class）
- MPPS の転送（PACS などへの N-CREATE の中継）
- 予定の無い撮影からの予約の作成（Patient の照合、予約の後付け）
- Performed Series Sequence の画像の一覧と、PACS にある画像との照合

## Decisions

### MWL と同じ AE で受ける

ADR-0001 の要点のとおり、`MwlServer.make_ae` に `ModalityPerformedProcedureStep` の
Presentation Context を足し、`evt.EVT_N_CREATE`・`evt.EVT_N_SET` の handler を足す。
モダリティの設定では MWL と MPPS の送り先を同じにすることが多く、AE を分けると試験の
環境の設定が増える。

### 予約は Accession Number と Scheduled Procedure Step ID の両方で探す

どちらもこの RIS が発番し、MWL で返した値。片方だけで探すと、受付番号が同じで
Scheduled Procedure Step が別の予約（この RIS では作らないが、他の RIS からの移行の
データ）を取り違える。Study Instance UID でも探せるが、モダリティによっては自分で
Study Instance UID を発番するので使わない。

### MPPS は別の表に記録し、状態の変更と同じトランザクションで書く

SQLite に `mpps` の表（`sop_instance_uid` が主キー、`status`、`accession_numbers`（JSON）、
`body`（受けた属性を pydicom の JSON にしたもの）、`created_at`、`updated_at`）を足す。
予約の状態の変更と MPPS の記録は、1つの `BEGIN IMMEDIATE` の中で行う。片方だけが
書かれると、MPPS が `COMPLETED` なのに予約が実施中のまま、という食い違いが残る。

受けた属性は、要求の Specific Character Set で文字列に直してから JSON にする
（F.7.2.2.3 の、N-SET の Specific Character Set は前の値を置き換えないという規則に、
文字列を Unicode で持つことで合わせる）。

### 遷移の表に無い MPPS は、成功を返して予約を変えない

終わりの状態の予約に MPPS が届いたとき、MPPS を断る（0110H など）案も考えた。
しかし PS3.4 F.7.2.1.3 は、SCP が予約の状態を理由に N-CREATE を断ることを定めていない。
断るとモダリティ側で送信のエラーが残り、撮影の記録（MPPS）も失われる。MPPS は記録し、
予約の状態は変えず、理由をログに出す。

### SOP Instance UID の無い N-CREATE は、SCP が発番する

PS3.4 F.7.2.1.2 は SCU が SOP Instance UID を指定するとするが、PS3.7 の N-CREATE は、
指定が無ければ SCP が発番して応答で返すことを許す。`2.25.` と UUID の整数で発番し、
応答の Affected SOP Instance UID で返す。

### 受けた値を検証する

ADR-0001 のとおり、相手から受けた値は信用しない。SOP Instance UID が PS3.5 9.1 の形でない、
Performed Procedure Step Status が Enumerated Values に無い、といった値は 0106H で断る。
処理の途中の想定外のエラーは 0110H にしてログに出し、SCP のスレッドは止めない。

## Risks / Trade-offs

- [中止を終わりの状態にすると、撮り直しの2つ目の MPPS で予約が戻らない] → 撮り直しは
  新しい予約を作る運用にする。中止から予定へ戻せる形が要るなら、`order-status` の
  遷移の表の変更として別の change で扱う
- [1つの予約に MPPS が2つあり、1つ目が `COMPLETED`、2つ目がまだ `IN PROGRESS`] → 1つ目で
  予約は完了になる。予約の詳細に MPPS の一覧と状態を出して、食い違いを見えるようにする
- [MPPS の表が増え続ける] → 試験の環境のツールなので消さない。データベースのファイルを
  消せば初期化できることを `docs/usage.md` に書く

## Migration Plan

1. 起動のときに `mpps` の表が無ければ作る（今の `orders`・`counters` と同じ方法）
2. 今のデータベースの予約はそのまま使える。中止の予約はまだ無い
3. 戻すときは、この change の commit を revert する。`mpps` の表は古い版では使われずに残る。
   中止にした予約は古い版では読めない（`OrderStatus` に無い）ので、戻す前に CLI で
   中止の予約が無いことを確かめるか、データベースを作り直す
