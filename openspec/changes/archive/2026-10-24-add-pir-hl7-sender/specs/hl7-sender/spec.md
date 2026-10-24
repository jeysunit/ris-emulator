# Spec Delta

## Purpose

PACS の PIR（Patient Information Reconciliation）への対応を試すために、RIS が HL7 v2.3.1 の
ADT^A40・ADT^A08・ORM^O01 を組み立て、MLLP で設定した宛先へ送り、ACK を受け取る。

## ADDED Requirements

### Requirement: ADT^A40 は正式の患者を PID に、旧い患者を MRG に入れる

統合のメッセージは ADT^A40^ADT_A39 とし、MSH・EVN・PID・MRG を持たなければならない
（SHALL）。PID-3 に正式な患者 ID、MRG-1 に旧い患者 ID を入れる。旧い患者 ID が空か、
正式な患者 ID と同じなら、組み立てずに断る（IHE RAD TF-2 4.12.4.4）。

#### Scenario: 仮 ID を正式な ID に統合する

- **WHEN** 患者 ID `P000001`、旧い患者 ID `ER0001` で A40 を組み立てる
- **THEN** PID-3 は `P000001^^^RIS_EMU^PI`、MRG-1 は `ER0001^^^RIS_EMU^PI` で、MSH-9 は `ADT^A40^ADT_A39`、EVN-1 は `A40` になる

#### Scenario: 旧い ID が正式な ID と同じ

- **WHEN** 旧い患者 ID を正式な患者 ID と同じにして A40 を組み立てる
- **THEN** 入力の誤りで断り、属性の更新は A08 を使うよう示す

### Requirement: ADT^A08 は患者の属性を送り、来院番号か患者アカウント番号を持つ

属性の更新のメッセージは ADT^A08^ADT_A08 とし、MSH・EVN・PID・PV1 を持たなければならない
（SHALL）。PID-18 か PV1-19 のどちらかに値がなければ、組み立てずに断る（IHE RAD TF-2
4.12.4.3.2.1.4）。PV1-19 を入れたら PV1-51 は `V` にする。

#### Scenario: 来院番号が無い

- **WHEN** 来院番号も患者アカウント番号も指定せずに A08 を組み立てる
- **THEN** 入力の誤りで断る

### Requirement: ORM^O01 は予約を NW で知らせる

予約のメッセージは ORM^O01^ORM_O01 とし、MSH・PID・PV1・ORC・OBR・ZDS を持たなければ
ならない（SHALL）。ORC-1 は `NW`、ORC-5 は `SC` にする。受付番号を OBR-18、Requested
Procedure ID を OBR-19、Scheduled Procedure Step ID を OBR-20、モダリティを OBR-24 に、
Study Instance UID を ZDS-1 に、発番した値のまま入れる（IHE RAD TF-2 4.4.4.1.2.1、
ADR-0003）。

#### Scenario: 予約を ORM にする

- **WHEN** 受付番号 `RE202610210001` の予約で ORM を組み立てる
- **THEN** ORC-1 は `NW`、OBR-18 は `RE202610210001`、ZDS-1 の先頭は予約の Study Instance UID になる

### Requirement: 値は HL7 の区切り文字をエスケープして入れる

欄に入れる値は、`|`・`^`・`~`・`&`・`\` を `\F\`・`\S\`・`\R\`・`\T\`・`\E\` にしなければ
ならない（SHALL）。制御文字（CR・LF・タブなど）を含む値は、組み立てずに断る。

#### Scenario: 区切り文字を含む氏名

- **WHEN** 氏名に `O&BRIEN|X` を含む患者で組み立てる
- **THEN** 受け手が `\T\`・`\F\` を戻すと `O&BRIEN|X` に復元でき、欄の数は変わらない

### Requirement: 氏名は表記ごとの XPN の繰り返しで送る

PID-5 には、空でない英字・漢字・かなのグループごとに XPN を作り、`~` でつなげて入れなければ
ならない（SHALL）。各 XPN の名前の種類は `L`、表記の種類は `A`・`I`・`P` にする。DICOM の PN の
接頭辞と接尾辞は、XPN の順（接尾辞、接頭辞）に入れ替える。氏名が空なら断る。

#### Scenario: 3 表記の氏名

- **WHEN** 英字 `YAMADA^TARO`、漢字 `山田^太郎`、かな `ヤマダ^タロウ` の患者で組み立てる
- **THEN** PID-5 は `YAMADA^TARO^^^^^L^A~山田^太郎^^^^^L^I~ヤマダ^タロウ^^^^^L^P` になる

### Requirement: 漢字を含むメッセージは UTF-8 で送り MSH-18 に示す

メッセージは UTF-8 で符号化しなければならない（SHALL）。ASCII 以外の文字があるときだけ
MSH-18 に `UNICODE UTF-8` を入れ、ASCII だけなら MSH-18 を空にする（IHE RAD TF-2 2.4.2.2）。

#### Scenario: ASCII だけの氏名

- **WHEN** 英字だけの氏名と ASCII だけの値で組み立てる
- **THEN** MSH-18 は空で、メッセージは ASCII だけになる

### Requirement: PID-3 の患者 ID は発番元を持つ

患者 ID・来院番号・患者アカウント番号の CX には、Assigning Authority の namespace ID を
入れなければならない（SHALL）。`orders.issuer_namespace` が空なら、組み立てずに断る
（IHE RAD TF-2 4.1.4.1.2.1.3）。

#### Scenario: 発番元が空

- **WHEN** `orders.issuer_namespace` を空にして A08 を送る
- **THEN** 設定の `orders.issuer_namespace` を空にしないよう示して断り、終了コードは 2 になる

### Requirement: MLLP で送り、ACK で結果を分ける

メッセージは `<VT>` 本文 `<FS><CR>` の枠で 1 通を送り、ACK を 1 通受け取らなければならない
（SHALL）。MSA-2 が送った MSH-10 と同じで、MSA-1 が `AA` なら受理、`AE`・`AR` なら拒否とする。
接続できない、時間切れ、枠が壊れている、ACK が 1 MiB を超える、MSH・MSA が読めない、MSA-2 が違う、
`AA`・`AE`・`AR` 以外の確認コードは失敗とする。通信の誤りは例外にせず結果で返す。

#### Scenario: 受け手が AA を返す

- **WHEN** スタブの受け手が、同じ MSH-10 を MSA-2 に入れた `AA` を返す
- **THEN** 結果は受理になり、受け手は送った本文をそのまま受け取っている

#### Scenario: 受け手が AR を返す

- **WHEN** スタブの受け手が `AR`、MSA-3 に理由を入れて返す
- **THEN** 結果は拒否になり、理由が結果に入る

#### Scenario: 受け手に接続できない

- **WHEN** 待ち受けていないポートへ送る
- **THEN** 結果は失敗になり、宛先のホストとポートが理由に入る

#### Scenario: 別のメッセージの ACK

- **WHEN** MSA-2 が送った MSH-10 と違う ACK が返る
- **THEN** 結果は失敗になり、MSA-2 が違うと示す

### Requirement: 宛先は設定の hl7 の節で決める

設定の `hl7` に、宛先（`host`・`port`）、MSH-3〜6 に入れる名前、MSH-11 の `processing_id`、
`timeout_seconds` を持つ。範囲外の値は、キーの位置を示して読み込まない。節が無い設定は
既定値（`127.0.0.1:2575`）で読む。

#### Scenario: ポートが範囲外

- **WHEN** `hl7.port: 70000` で起動する
- **THEN** 設定のエラーになり、`hl7.port` の位置が示される

### Requirement: CLI の pir send で組み立てて送る

`pir send --kind a40|a08|orm` で、メッセージを組み立てて送らなければならない（SHALL）。
`--dry-run` は組み立てたメッセージを出すだけで、ネットワークを使わない。終了コードは、受理が 0、
入力・設定の誤りが 2、予約が無いが 3、拒否が 5、通信の失敗が 6。

#### Scenario: 拒否された

- **WHEN** 受け手が AR を返す
- **THEN** 終了コードは 5 で、標準エラーに確認コードと理由が出る
