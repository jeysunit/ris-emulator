# 07. 照合（Reconciliation）

予約の無い撮影（緊急の飛び込みなど）は、モダリティが仮の患者ID と氏名で撮影し、
MPPS だけが記録される（[05_mpps_scp.md](05_mpps_scp.md) の 2 章）。照合は、その撮影に
正式な患者と新しい予約を結び、結果を HL7 v2.3.1 で PACS に知らせる。PACS 側の
PIR（Patient Information Reconciliation）への対応を試す相手にするための機能で、
HL7 の組み立てと送信は [06_hl7_pir.md](06_hl7_pir.md) にある。設計の理由は
[ADR-0011](../decisions/0011-reconciliation-links-the-mpps.md) にある。

## 1. 対象：未照合の撮影

予約に結び付いていない MPPS を、未照合の撮影とする。MPPS の記録の「結び付いた受付番号」
が空のものである。N-CREATE の Scheduled Step Attributes Sequence の項目が、予約と
一致しなかった場合（受付番号が空、または一致する予約が無い）に当たる。

MPPS の状態（`IN PROGRESS`・`COMPLETED`・`DISCONTINUED`）によらず照合できる。
一覧は受けた順に並べる。

## 2. MPPS から読む値

| 値 | 読み取り元 |
|----|------------|
| 仮の患者ID・氏名・生年月日・性別 | Patient ID (0010,0020)・Patient's Name (0010,0010)・Patient's Birth Date (0010,0030)・Patient's Sex (0010,0040) |
| Study Instance UID | Scheduled Step Attributes Sequence (0040,0270) の項目のうち、最初の空でない Study Instance UID (0020,000D) |
| モダリティ | Modality (0008,0060) |
| 装置 | Performed Station AE Title (0040,0241)・Performed Station Name (0040,0242) |
| 撮影の開始日時 | Performed Procedure Step Start Date (0040,0244)・Time (0040,0245) |

読めない値は空として扱う。生年月日と開始日時は、`YYYYMMDD`・`HHMMSS`
（秒の小数は捨てる）の形のときだけ使う。性別は `M`・`F`・`O` のときだけ使う。
装置の AEタイトルは AE の規則（[01_orders.md](01_orders.md) の台帳の `ae_title`）に
合うときだけ使う。`\` で区切られた複数の値を持つ属性は、空として扱う。

次のときは照合できない。一覧には出し、画面と CLI は理由を示す。

| 理由 | 条件 |
|------|------|
| Study Instance UID が無い | Scheduled Step Attributes Sequence に空でない値が無い |
| 仮の患者ID が無い | Patient ID が空 |
| 仮の患者ID を HL7 に入れられない | 患者ID の規則（[04_identifiers.md](04_identifiers.md)）に合わない |
| 氏名を読めない | コンポーネントグループが 64 字を超えるなど |
| モダリティが設定に無い | `orders.modalities` に Modality が無い（確定のときに断る） |

## 3. 照合の確定

### 3.1 入力

| 項目 | 内容 |
|------|------|
| 正式な患者 | 名簿の患者を選ぶか、患者ID・氏名（英字・漢字・かな）・生年月日・性別を入力する |
| 検査名 | MPPS のモダリティの `procedures` から選ぶ。省略するとその先頭 |
| 依頼科 | `departments` から選ぶ（CLI は任意の LO）。省略すると「救急科」（無ければ先頭） |

生年月日は実在する日付でなければ断る。

### 3.2 作る予約

| 項目 | 値 |
|------|----|
| 受付番号・Requested Procedure ID・Scheduled Procedure Step ID | [01_orders.md](01_orders.md) の 2 章と同じ採番（同じ連番を使う） |
| Study Instance UID | **MPPS の値のまま。新しく発番しない**（PIR では Study Instance UID が撮影・画像・HL7 を結ぶ鍵になる。[ADR-0004](../decisions/0004-ris-issues-study-instance-uid.md) の例外） |
| 患者 | 正式な患者 |
| モダリティ | MPPS の Modality |
| 予定の AEタイトル・装置名・装置 | MPPS の Performed Station AE Title が台帳にあれば、その台帳の装置。台帳に無ければ MPPS の値（装置の名前は空）。MPPS に無ければ台帳の先頭 |
| 予定日時 | MPPS の開始日時。読めなければ、照合した日時 |
| 優先度 | `STAT`（予約の無い撮影は緊急の飛び込みとして扱う） |
| 状態 | MPPS の状態に合わせる：`IN PROGRESS`=実施中、`COMPLETED`=完了、`DISCONTINUED`=中止 |
| 文字コード・施設名・発番元 | 設定の既定 |

予約の作成、MPPS の結び付け（記録の受付番号に新しい予約を足す）、照合の記録、
送る HL7 の組み立てを、1 つのトランザクションで行う。仮の患者の値と、送る HL7 の種類は、
トランザクションの中で読み直した MPPS から決める（確定の直前に N-SET が患者の値を変えても、
旧い患者ID と送る種類が予約と食い違わない）。どこかで誤りがあれば何も残さず、連番も
使わない。

結び付けた後に届く N-SET は、新しい予約の状態を [05_mpps_scp.md](05_mpps_scp.md) の
3 章と同じに進める（実施中で照合した撮影が、後から完了になると、予約も完了になる）。

### 3.3 断る場合

- MPPS が無い：断る（画面は 404、CLI は終了コード 3）
- MPPS がすでに予約に結び付いている（照合済み、または予約どおりの撮影）：断り、
  何も変えない（画面は 409、CLI は終了コード 2）
- 入力の誤り、照合できない撮影（2 章）、HL7 に入れられない値（氏名が空、
  `orders.issuer_namespace` が空など）：断り、何も残さない（画面は 400、CLI は終了コード 2）

### 3.4 照合の後に届く撮影

照合の後も、モダリティが仮の患者のまま同じ Study で撮ることがある（IHE PIR の
Case 6。DTG の緊急の患者の追加撮影）。この撮影の MPPS は、N-CREATE のときに照合で
作った予約に結び付ける（[05_mpps_scp.md](05_mpps_scp.md) の 2 章の 5）。条件は次の
すべてである。設計の理由は [ADR-0012](../decisions/0012-case6-and-procedure-update.md)
にある。

- Scheduled Step Attributes Sequence の項目の Accession Number が空
- その項目の Study Instance UID が、照合で作った予約の Study Instance UID と同じ
- MPPS の Patient ID が、その照合の仮の患者ID か、予約の正式な患者ID と同じ

結び付いた MPPS は未照合の一覧に出ず、予約の詳細の MPPS の表に並ぶ。予約の状態は
[05_mpps_scp.md](05_mpps_scp.md) の 4 章の規則で変える（完了の予約は、N-CREATE で
実施中に戻らない）。PACS へは何も送らない。照合で作っていない予約、患者ID が合わない
撮影、受付番号が入っていて一致しない項目は結び付けない（未照合の一覧に出る）。

## 4. 送る HL7

### 4.1 種類と順序

| 条件 | 送るもの（この順） |
|------|--------------------|
| 正式な患者ID が仮の患者ID と違う | ADT^A40（PID が正式な患者、MRG-1 が仮の患者ID、MRG-7 が仮の氏名）、ORM^O01（NW） |
| 患者ID が同じで、氏名・生年月日・性別のどれかが違う | ADT^A08、ORM^O01（NW） |
| すべて同じ | ORM^O01（NW）だけ |

- 患者区分（PV1-2）は `E`（救急）。A08 と ORM の来院番号（PV1-19）は受付番号
- 氏名の比較は DICOM の PN の形（`英字=漢字=かな`）で行う
- メッセージの中身は [06_hl7_pir.md](06_hl7_pir.md) の規則どおり。MSH-7 と MSH-10 は
  照合を確定したときに決まり、送り直しても変わらない

### 4.2 送信と記録

確定の後、宛先（設定の `hl7`）へ 1 通ずつ順に送る。**受理（AA）されなかった 1 通で止め、
次の通は送らない**（統合の前に予約を知らせないため）。

各通の記録は、組み立てた本文・MSH-10・結果・ACK の確認コードと理由・送信日時・送った
回数である。結果は次の 4 つ。

| 結果 | 内容 | 画面の名前 |
|------|------|------------|
| pending | まだ送っていない（前の通が受理されなかった） | 送信待ち |
| accepted | AA | 送信完了 |
| rejected | AE・AR | 拒否 |
| failed | 接続できない、時間切れ、枠・ACK の誤りなど（[06_hl7_pir.md](06_hl7_pir.md) の 4 章） | 送信失敗 |

- 送る前に、その通を送る権利を取り、送った回数を 1 つ増やす。他のプロセス（画面・CLI）が
  同じ通を送っている間（送信の時間切れの 2 倍に 5 秒を足した時間まで）は、その通を送らずに
  止める。結果を書くと権利は外れる。これで、再送信の二重の操作が同じ通を重ねて送らない
- 拒否・失敗でも照合は取り消さない。予約と結び付けは残る
- 再送信は、受理されていない通を、記録した**同じ本文**（同じ MSH-10）で、先頭から順に
  送る。受理済みの通は送らない。同じ送り手・同じ MSH-10 の再送には、受け手が前と同じ
  ACK を返せる
- 相手の ACK の値は、制御文字などを `\uXXXX` にしてから記録し、表示する
  （[06_hl7_pir.md](06_hl7_pir.md) の 4 章と同じ理由）

### 4.3 照合で作った予約の取消・中止

照合で作った予約を、画面（予約の状態の変更）か CLI（`status`）で取消・中止にしたら、
ORM^O01 を 1 通、照合の記録の送信の末尾に足して送る（IHE RAD TF-2 4.13 の Procedure
Update）。

| 変えた状態 | 送るもの | 画面・CLI のメッセージの名前 |
|------------|----------|------------------------------|
| 取消 | ORM^O01（ORC-1 が `CA`） | ORM^O01（CA） |
| 中止 | ORM^O01（ORC-1 が `DC`） | ORM^O01（DC） |

- 状態の変更と通の追加は 1 つのトランザクションで行う。組み立てに失敗したら、状態も
  変えない
- 記録は 4.2 と同じ。前の通（NW など）がすべて受理されていれば、足した通を送る。
  受理されていない通があれば何も送らず、足した通は送信待ちで残る。前の通の送り直しは
  再送信の操作で行い、先頭から順に送る（予約を知らせる前に取消を送らない）
- 同じ状態の指定（何もしない）では足さない
- 照合で作っていない予約と、MPPS の N-SET（`DISCONTINUED`）による中止では送らない
- CLI の `status` は、送った通の結果を出し、拒否があれば終了コード 5、失敗があれば 6
- XO（変更）は自動では送らない。CLI の `pir send --order-control XO` で送れる
  （[06_hl7_pir.md](06_hl7_pir.md) の 5 章）

## 5. Web 画面

| パス | 内容 |
|------|------|
| `/reconciliation` | 未照合の撮影の一覧：件数の行と、受けた日時・状態（MPPS。実施中・完了・中止の札）・患者ID・氏名・生年月日・性別・モダリティ・予定の AEタイトル・Study Instance UID。行ごとの「照合」で次の画面へ。無いときは表の見出しを残して「未照合の撮影はありません。」と次の手を出す |
| `/reconciliation/<SOP Instance UID>` | 照合（画面の型 C。パンくず・仮の患者の患者バナー・区画・操作の行「キャンセル」「照合・送信」）：撮影の値と、正式な患者（名簿から選ぶ・入力する）・検査（検査名・依頼科）のフォーム。「照合・送信」で確定し、予約の詳細へ進む。誤りは同じ画面に示し、入力を残す。照合済みなら予約へのリンクを出す。照合できない撮影は理由を出し、フォームを出さない |
| `/orders/<受付番号>/hl7/resend` | POST。再送信（4.2）して予約の詳細へ戻る |

- ナビに「未照合」を足す
- 照合で作った予約の詳細に、「照合前の患者ID」「照合前の氏名」と、表「HL7 送信」
  （メッセージ・状態・ACK・詳細・送信日時・回数）を出す。受理されていない通があれば
  「再送信」のボタンを出す。照合で作っていない予約には出さない
- 画面の名前は [openspec の screen-terms](../../openspec/specs/screen-terms/spec.md) に従い、
  「患者ID」「氏名」を使う。画面に説明の文は置かない
- 書き込み（POST）は [03_web_cli.md](03_web_cli.md) の 3.3 の CSRF・origin の検査を受ける

## 6. CLI

| サブコマンド | 内容 |
|--------------|------|
| `reconcile list` | 未照合の撮影の一覧。`--json` |
| `reconcile run <SOP Instance UID>` | 照合を確定して HL7 を送る。正式な患者は `--roster-patient-id`（名簿）か、`--patient-id` と `--name`（`英字=漢字=かな`。`--birth-date`・`--sex` を足せる）。`--procedure`・`--department`・`--json` |
| `reconcile resend <受付番号>` | 受理されていない HL7 を、同じ本文で順に送り直す。`--json` |

`run` と `resend` の終了コードは、HL7 がすべて受理されれば 0、拒否（AE・AR）があれば 5、
失敗（通信・ACK の誤り）があれば 6。それ以外は [03_web_cli.md](03_web_cli.md) の 2 章と同じ
（入力の誤りと照合済みは 2、MPPS・照合の記録が無いときは 3）。

## 7. 保存

データベースの `reconciliations` の表に、受付番号（主キー）・MPPS の SOP Instance UID
（重ならない）・記録（仮の患者の値と、各通の送信の記録の JSON）・作成日時・更新日時を置く。
表は起動のときに無ければ作る。古いデータベースは、そのまま読める。

## 8. 原典と、確認していないこと

- IHE Radiology Technical Framework Rev. 23.0：Volume 1 の 4（PIR。Case 3・5 が予約の
  無い撮影）、Volume 2 の 4.4（Procedure Scheduled。事後の受付番号の上書きと、
  モダリティが発番した Study Instance UID を残すこと）・4.12（Patient Update）
  <https://www.ihe.net/uploadedFiles/Documents/Radiology/IHE_RAD_TF_Vol2.pdf>
- HL7 v2.3.1 Table 0004（患者区分）の `E`（救急）

確認していないこと：

- 統合（A40）の後に ORM の NW を送る順序と、A08 で足りる場合に統合を送らないことが、
  原典の必須の規則かどうかは確認していない。PIR の流れ（仮の ID で撮影、統合、予約の
  知らせ）に沿って決めた
- 優先度 `STAT`、患者区分 `E` を、予約の無い撮影に付けることは、この RIS の判断で、
  原典の規定ではない
