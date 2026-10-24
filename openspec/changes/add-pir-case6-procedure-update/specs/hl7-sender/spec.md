# Spec Delta

## MODIFIED Requirements

### Requirement: ORM^O01 は予約を NW で知らせる

予約のメッセージは ORM^O01^ORM_O01 とし、MSH・PID・PV1・ORC・OBR・ZDS を持たなければ
ならない（SHALL）。ORC-1 は既定で `NW`、ORC-5 は `SC` にする。取消・中止・変更を
知らせるときは ORC-1 を `CA`・`DC`・`XO` にし（IHE RAD TF-2 4.13）、ORC-5 は `CA`・`DC`、
`XO` では予約のいまの状態の値（`SC`・`IP`・`CM`・`CA`・`DC`）にする。ほかの ORC-1 は
組み立てずに断る（SHALL）。受付番号を OBR-18、Requested Procedure ID を OBR-19、
Scheduled Procedure Step ID を OBR-20、モダリティを OBR-24 に、Study Instance UID を
ZDS-1 に、発番した値のまま入れる（IHE RAD TF-2 4.4.4.1.2.1、ADR-0003）。

#### Scenario: 予約を ORM にする

- **WHEN** 受付番号 `RE202610210001` の予約で ORM を組み立てる
- **THEN** ORC-1 は `NW`、OBR-18 は `RE202610210001`、ZDS-1 の先頭は予約の Study Instance UID になる

#### Scenario: 取消を ORM にする

- **WHEN** ORC-1 を `CA` にして ORM を組み立てる
- **THEN** ORC-1 と ORC-5 は `CA` になり、ほかの欄は NW と同じになる

#### Scenario: 知らない ORC-1

- **WHEN** ORC-1 を `XX` にして ORM を組み立てる
- **THEN** 入力の誤りで断る
