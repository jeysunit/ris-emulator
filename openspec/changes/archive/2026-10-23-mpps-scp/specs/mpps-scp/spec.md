# Spec Delta

## Purpose

モダリティから MPPS（Modality Performed Procedure Step）の N-CREATE・N-SET を受け、
PS3.4 F.7 の SCP として応答し、撮影の開始・完了・中止を予約の状態に反映する。

## ADDED Requirements

### Requirement: MPPS の SOP Class を MWL と同じ AE で受ける

MWL の SCP は、Modality Performed Procedure Step SOP Class（1.2.840.10008.3.1.2.3.3）の
SCP として、N-CREATE と N-SET を受けなければならない（SHALL。PS3.4 F.7.2）。AE タイトル・
ポート・Called AE Title の検証は MWL と同じ設定を使う。

#### Scenario: MPPS の Association を受ける

- **WHEN** モダリティが、MWL の AE タイトルとポートへ、MPPS の SOP Class の Presentation Context を提案する
- **THEN** その Presentation Context は受け入れられる

### Requirement: N-CREATE は IN PROGRESS だけを受ける

N-CREATE の Performed Procedure Step Status (0040,0252) が `IN PROGRESS` でなければ、
0106H（Invalid Attribute Value）で断らなければならない（SHALL。PS3.4 F.7.2.1.3）。
同じ SOP Instance UID の MPPS がすでにあれば 0111H（Duplicate SOP Instance）で断る（PS3.7）。
断った MPPS は記録せず、予約も変えない。

#### Scenario: COMPLETED で N-CREATE する

- **WHEN** モダリティが、Performed Procedure Step Status を `COMPLETED` にした N-CREATE を送る
- **THEN** 応答の Status は 0106H になり、予約の状態は変わらない

#### Scenario: 同じ SOP Instance UID で2回 N-CREATE する

- **WHEN** モダリティが、受け付けた MPPS と同じ SOP Instance UID で N-CREATE を送る
- **THEN** 応答の Status は 0111H になる

### Requirement: MPPS と予約を結び付ける

N-CREATE の Scheduled Step Attributes Sequence (0040,0270) の項目ごとに、Accession Number
(0008,0050) と Scheduled Procedure Step ID (0040,0009) の両方が一致する予約を探し、MPPS に
結び付けなければならない（SHALL）。1つの MPPS に複数の予約が結び付いてよい。一致する
予約が無い項目は、予定の無い撮影として MPPS だけを記録する。

#### Scenario: 予約を撮影する

- **WHEN** 予定の予約の受付番号と Scheduled Procedure Step ID を Scheduled Step Attributes Sequence に入れた N-CREATE（IN PROGRESS）が届く
- **THEN** 応答の Status は 0000H になり、予約の状態は実施中になる

#### Scenario: 2件の予約をまとめて撮影する

- **WHEN** 2件の予約の項目を Scheduled Step Attributes Sequence に入れた N-CREATE（IN PROGRESS）が届く
- **THEN** 2件とも実施中になる

#### Scenario: 予定の無い撮影

- **WHEN** Scheduled Procedure Step ID が空で、どの予約にも一致しない N-CREATE（IN PROGRESS）が届く
- **THEN** 応答の Status は 0000H になり、MPPS は記録され、どの予約も変わらない

### Requirement: 終わりの状態の予約は MPPS で変えない

結び付いた予約が終わりの状態（完了・取消・中止）か、MPPS が求める向きの遷移が `order-status` の
遷移の表に無いときは、予約の状態を変えずに MPPS の処理を成功にしなければならない（SHALL）。
MPPS はそのまま記録し、変えなかった予約と理由をログに出す。

#### Scenario: 取消の予約の MPPS

- **WHEN** 取消の予約に一致する N-CREATE（IN PROGRESS）が届く
- **THEN** 応答の Status は 0000H になり、予約は取消のままになる

### Requirement: N-SET は IN PROGRESS の MPPS だけを更新する

N-SET の対象の SOP Instance UID の MPPS が無ければ 0112H（No Such SOP Instance。PS3.7）、記録した
Performed Procedure Step Status が `IN PROGRESS` でなければ 0110H（Processing Failure）と
Error ID A710 で断らなければならない（SHALL。PS3.4 F.7.2.2.3、Table F.7.2-2）。

#### Scenario: 完了した MPPS を更新しようとする

- **WHEN** `COMPLETED` にした MPPS に、もう一度 N-SET が届く
- **THEN** 応答の Status は 0110H、Error ID は A710 になり、MPPS と予約は変わらない

#### Scenario: 知らない MPPS を更新しようとする

- **WHEN** 受けていない SOP Instance UID の N-SET が届く
- **THEN** 応答の Status は 0112H になる

### Requirement: N-SET の完了と中止を予約に反映する

N-SET で Performed Procedure Step Status が `COMPLETED` になったら、結び付いた予約を完了に、
`DISCONTINUED` になったら中止にしなければならない（SHALL）。状態を含まない N-SET は、
受けた属性を記録だけする。

#### Scenario: 撮影を終える

- **WHEN** 実施中の予約に結び付いた MPPS に、Performed Procedure Step Status を `COMPLETED` にした N-SET が届く
- **THEN** 応答の Status は 0000H になり、予約は完了になり、MWL で返らなくなる

#### Scenario: 撮影を中止する

- **WHEN** 実施中の予約に結び付いた MPPS に、Performed Procedure Step Status を `DISCONTINUED` にした N-SET が届く
- **THEN** 応答の Status は 0000H になり、予約は中止になる

### Requirement: 受けた MPPS を記録して表示する

受け付けた MPPS ごとに、SOP Instance UID・Performed Procedure Step Status・受けた日時・
結び付いた受付番号・受けた属性を、予約とは別に記録しなければならない（SHALL）。予約の
詳細には、結び付いた MPPS の SOP Instance UID・状態・受けた日時を表示する。

#### Scenario: 予約の詳細に MPPS が出る

- **WHEN** 予約に結び付いた MPPS を `COMPLETED` まで受けてから、予約の詳細を開く
- **THEN** その MPPS の SOP Instance UID と「COMPLETED」が表示される
