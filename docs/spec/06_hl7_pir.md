# 06. HL7 v2.3.1 の送信（PIR）

PACS の PIR（Patient Information Reconciliation）への対応を試すために、HL7 v2.3.1 の
メッセージを組み立て、MLLP で設定した宛先へ送る。送るのは次の 3 種類で、受信はしない
（[project_charter.md](../project_charter.md) の 2 章）。選んだ形式の理由は
[ADR-0010](../decisions/0010-hl7-sender-format.md) にある。

## 1. 送るメッセージ

| メッセージ | IHE RAD TF-2 | 使う場面 | セグメント |
|------------|--------------|----------|------------|
| ADT^A40^ADT_A39 | 4.12.4.4（Patient Update [RAD-12]） | 仮の患者 ID で撮った検査を、正式な患者 ID に統合する。PID が正式の患者、MRG が旧い患者 | MSH・EVN・PID・MRG |
| ADT^A08^ADT_A08 | 4.12.4.3（RAD-12） | 患者の氏名・生年月日・性別を更新する。患者 ID は更新できない（A40 を使う） | MSH・EVN・PID・PV1 |
| ORM^O01^ORM_O01 | 4.4.4.1.2.1（Procedure Scheduled [RAD-4]） | 予約を知らせる。ORC-1 は `NW` | MSH・PID・PV1・ORC・OBR・ZDS |

どれも HL7 のオリジナルモードで確認を求める（MSH-15・MSH-16 は空。IHE RAD TF-2 2.4.1.2）。
A02・A03・A06・A07、ORM の `CA`・`DC`・`XO`（RAD-13）、HL7 v2.5.1 の OMI は送らない。

## 2. 組み立ての規則

### 2.1 MSH

| 欄 | 値 |
|----|----|
| MSH-3〜6 | 設定の `hl7.sending_application`・`sending_facility`・`receiving_application`・`receiving_facility` |
| MSH-7 | 組み立てた時刻 `YYYYMMDDHHMMSS`（時差は付けない。プロセスの時計の時刻） |
| MSH-9 | `ADT^A40^ADT_A39`・`ADT^A08^ADT_A08`・`ORM^O01^ORM_O01`（3 つめは IHE が許す。A40 は `ADT_A39`） |
| MSH-10 | `yyMMddHHmmss` に乱数 8 桁（16 進）を足した 20 文字 |
| MSH-11 | 設定の `hl7.processing_id`（`P`・`T`・`D`） |
| MSH-12 | `2.3.1` |
| MSH-18 | メッセージに ASCII 以外の文字があるときだけ `UNICODE UTF-8`。ASCII だけなら空（IHE RAD TF-2 2.4.2.2） |

メッセージは UTF-8 で符号化する。MSH-20（文字集合の切り替え）は使わない。

### 2.2 区切りとエスケープ

区切りは MSH-1・MSH-2 の推奨値（`|`、`^~\&`）で、セグメントの区切りは CR。値は
欄に入れる前に、`|` を `\F\`、`^` を `\S\`、`&` を `\T\`、`~` を `\R\`、`\` を `\E\` に
する。CR・LF・タブなどの制御文字を含む値は、組み立てずに断る（セグメントの区切りと
MLLP の枠が壊れるため）。氏名の `^` だけは、DICOM の PN でもコンポーネントの区切りなので、
HL7 のコンポーネントの区切りとして扱う。

### 2.3 識別子

- 患者 ID・来院番号・患者アカウント番号は CX にする：`<ID>^^^<発番元>^<種類>`。発番元は
  `orders.issuer_namespace`（Assigning Authority の namespace ID。IHE RAD TF-2
  4.1.4.1.2.1.3 が必須とするので、空なら断る）。種類は患者 ID が `PI`、来院番号が `VN`、
  患者アカウント番号が `AN`
- ORM の受付番号は OBR-18、Requested Procedure ID は OBR-19、
  Scheduled Procedure Step ID は OBR-20 に、発番した値のまま入れる（英数字だけなので、エスケープは何も変えない。
  [ADR-0003](../decisions/0003-identifiers-fit-dicom-and-hl7.md)）
- Study Instance UID は ZDS-1 に `<UID>^<送り手のアプリケーション名>^Application^DICOM` で入れる
  （IHE RAD TF-2 Table 4.4-8）

### 2.4 氏名（PID-5）

英字・漢字・かなのグループごとに 1 つの XPN を作り、`~` でつなぐ。各 XPN の名前の種類
（7 つめ）は `L`（正式名）、表記の種類（8 つめ）は英字が `A`、漢字が `I`、かなが `P`。
空のグループは送らない。DICOM の PN の `姓^名^ミドル^接頭辞^接尾辞` は、XPN の
`姓^名^ミドル^接尾辞^接頭辞` の順に入れ替える。どの成分にも空白以外の文字が無ければ（`^^^^` や空白だけを含む）断る（PID-5 は必須）。
生年月日（PID-7）は空か、実在する日付の ASCII の `YYYYMMDD` に限り、それ以外は断る。
旧い患者 ID（MRG-1）にも、正式な患者 ID と同じ規則（64 文字まで、`\`・制御文字・
`^~&|`・前後の空白なし）を使う。

### 2.5 PV1 と来院番号

PV1-2 は患者区分（既定 `O`=外来。救急は `E`）。PV1-19 に来院番号を入れたら PV1-51 は `V`。
IHE は PID-18 か PV1-19 のどちらかに値を求めるので、A08 と ORM は、どちらも無ければ
断る。ORM で来院番号を指定しない CLI は、受付番号を来院番号に使う。A40 は PV1 が任意なので付けない。
ORM の PV1-8 には、紹介医を英字（無ければ漢字、かな）の 1 表記で入れる。

### 2.6 ORM の ORC・OBR

| 欄 | 値 |
|----|----|
| ORC-1・ORC-5 | `NW`・`SC` |
| ORC-2・OBR-2 | 空（発注元の番号を持たない） |
| ORC-3・OBR-3 | `<受付番号>^<発番元>`（Filler Order Number） |
| ORC-7・OBR-27 | `^^^<予定日時>`（4 つめのコンポーネントが開始日時） |
| ORC-12・OBR-16 | 依頼医（XCN。ID は空） |
| OBR-4 | `<検査コード>^<検査名>^<コード体系>` を 2 回（1〜3 つめが Universal Service ID、4〜6 つめが Scheduled Protocol Code） |
| OBR-5 | 優先度：`STAT`→`S`、`HIGH`→`A`、`ROUTINE`→`R`。それ以外は空 |
| OBR-24 | モダリティ |
| OBR-44 | `<検査コード>^<検査名>^<コード体系>` |

## 3. 例

患者 `P000001`（名簿の例）。MSH-10 と時刻は例のために固定した。受け手と共有する
ために、実際に組み立てた出力をそのまま載せている（セグメントごとに改行）。

ADT^A40（旧い患者 ID `ER2026102400` を `P000001` に統合する）：

```text
MSH|^~\&|RIS_EMU|TEST_HOSPITAL|PACS|PACS|20261024201530||ADT^A40^ADT_A39|20261024201530A40A|P|2.3.1||||||UNICODE UTF-8
EVN|A40|20261024201530
PID|1||P000001^^^RIS_EMU^PI||TANAKA^HIROSHI^^^^^L^A~田中^博^^^^^L^I~タナカ^ヒロシ^^^^^L^P||19980312|M
MRG|ER2026102400^^^RIS_EMU^PI||||||UNKNOWN^MALE^^^^^L^A
```

ADT^A08（属性の更新。来院番号 `V20261024001`）：

```text
MSH|^~\&|RIS_EMU|TEST_HOSPITAL|PACS|PACS|20261024201530||ADT^A08^ADT_A08|20261024201531A08A|P|2.3.1||||||UNICODE UTF-8
EVN|A08|20261024201530
PID|1||P000001^^^RIS_EMU^PI||TANAKA^HIROSHI^^^^^L^A~田中^博^^^^^L^I~タナカ^ヒロシ^^^^^L^P||19980312|M
PV1|1|O|||||||||||||||||V20261024001^^^RIS_EMU^VN||||||||||||||||||||||||||||||||V
```

ORM^O01（受付番号 `RE202610210001` の予約）：

```text
MSH|^~\&|RIS_EMU|TEST_HOSPITAL|PACS|PACS|20261024201530||ORM^O01^ORM_O01|20261024201532ORMA|P|2.3.1||||||UNICODE UTF-8
PID|1||P000001^^^RIS_EMU^PI||TANAKA^HIROSHI^^^^^L^A~田中^博^^^^^L^I~タナカ^ヒロシ^^^^^L^P||19980312|M
PV1|1|O||||||^SHIMIZU^ISAMU|||||||||||RE202610210001^^^RIS_EMU^VN||||||||||||||||||||||||||||||||V
ORC|NW||RE202610210001^RIS_EMU||SC||^^^20261021090000|||||^SHIMIZU^ISAMU
OBR|1||RE202610210001^RIS_EMU|CT0003^腹部 CT 造影^99RISEMU^CT0003^腹部 CT 造影^99RISEMU|R|||||||||||^SHIMIZU^ISAMU||RE202610210001|RP202610210001|SPS202610210001||||CT|||^^^20261021090000|||||||||||||||||CT0003^腹部 CT 造影^99RISEMU
ZDS|2.25.67256859653214869994870466343258677753^RIS_EMU^Application^DICOM
```

## 4. MLLP と ACK

- 枠は `<VT>` 本文 `<FS><CR>`（0x0B、0x1C 0x0D。HL7 Implementation Guide 付録 C。
  IHE RAD TF-2 2.4.1.1 が使うよう求めている）
- 送り手が接続を開き、1 通を送り、ACK を 1 通受け取って閉じる。再接続や再送はしない
- ACK は枠を外して読み、MSA-1・MSA-2・MSA-3 と ERR-1 を取る。MSH-1・MSH-2 は
  推奨値（`|^~\&`）でなければならず、MSA-2 は送った MSH-10 と同じでなければならない
- `timeout_seconds` は、接続と、ACK を受け終えるまでの全体の秒数。少しずつ返す相手でも
  超えれば失敗にする
- 結果は次の 3 つに分ける

| 結果 | 条件 | CLI の終了コード |
|------|------|------------------|
| 受理（accepted） | MSA-1 が `AA` | 0 |
| 拒否（rejected） | MSA-1 が `AE` または `AR`。ERR-1 か MSA-3 を理由にする | 5 |
| 失敗（failed） | 接続できない、時間切れ、枠が壊れている、ACK が大きすぎる（1 MiB 超）、MSH・MSA が読めない、MSA-2 が違う、`AA`・`AE`・`AR` 以外のコード（`CA`・`CE`・`CR` を含む） | 6 |

通信の誤りは例外にせず結果で返す。呼び出し側が「失敗」として記録し、再送できるようにするため。

## 5. CLI と設定

```bash
# 組み立てるだけ（送らない）
python -m app.cli pir send --kind a40 --patient-id P000001 --prior-patient-id ER2026102400 \
    --name "TANAKA^HIROSHI=田中^博=タナカ^ヒロシ" --birth-date 19980312 --sex M --dry-run
# 送る
python -m app.cli pir send --kind a08 --patient-id P000001 --name "TANAKA^HIROSHI" --visit-number V20261024001
python -m app.cli pir send --kind orm --accession RE202610210001 --patient-class E
```

| オプション | 内容 |
|------------|------|
| `--kind` | `a40`・`a08`・`orm`（必須） |
| `--patient-id`・`--name` | a40・a08：患者 ID と氏名（`英字=漢字=かな`、各グループは `姓^名^ミドル^接頭辞^接尾辞`）。`--birth-date`・`--sex` を足せる |
| `--prior-patient-id`・`--prior-name` | a40：旧い患者 ID（必須）と氏名 |
| `--accession` | orm：保存済みの予約の受付番号（患者・検査・UID は予約から取る） |
| `--visit-number`・`--account-number`・`--patient-class` | PV1-19、PID-18（a08）、PV1-2 |
| `--host`・`--port` | 設定の `hl7.host`・`hl7.port` を上書きする |
| `--dry-run` | 組み立てたメッセージを標準出力に出して終わる（ネットワークを使わない） |

設定の `hl7`（[03_web_cli.md](03_web_cli.md) の 4 章）：`host`（既定 `127.0.0.1`）・`port`
（`2575`）・`sending_application`（`RIS_EMU`）・`sending_facility`（`TEST_HOSPITAL`）・
`receiving_application`・`receiving_facility`（どちらも `PACS`）・`processing_id`（`P`）・
`timeout_seconds`（`10`。接続と ACK の待ち時間）。MSH-3〜6 は 1〜180 文字で、制御文字を含めない。
終了コードは 2=入力・設定の誤り（患者 ID の区切り文字、旧い ID が正式の ID と同じ、
`issuer_namespace` が空など）、3=予約が無い。

## 6. 原典と、確認していないこと

- IHE Radiology Technical Framework Volume 2 Rev. 23.0（2025-08-08）：2.4（HL7 の実装の
  注意。Table 2.4-2 の MSH、Table 2.4-3 の MSA）、4.1.4.1.2.1（EVN・PID・PV1）、
  4.4.4.1.2.1（ORM の Table 4.4-2〜4.4-8）、4.12.4.3・4.12.4.4（A08・A40）
  <https://www.ihe.net/uploadedFiles/Documents/Radiology/IHE_RAD_TF_Vol2.pdf>
- IHE Radiology Technical Framework Volume 1 Rev. 23.0：4.1（PIR のアクターとトランザクション）
- HL7 v2.3.1 の原典（セグメントの欄の定義、エスケープ、データ型）は読んでいない。
  上の IHE の表と、その中の記述から組み立てた。次の点は HL7 の原典で確認していない
  - XPN の 8 つめ（表記の種類 `A`・`I`・`P`）が v2.3.1 にあるか。受け手が読み取れない
    ときは、順番（英字、漢字、かな）で判断する
  - CX の 5 つめ（`PI`・`VN`・`AN`）が HL7 Table 0203 の値として v2.3.1 にあるか
  - MSH-18 の `UNICODE UTF-8` が v2.3.1 の Table 0211 にあるか。IHE の MSH-18 の節
    （v2.5.1 向け）が例に挙げている
  - IHE の v2.3.1 の表にある欄の長さ（PID-3 は 20、PID-5 は 48 など）は守っていない。
    `<ID>^^^<発番元>^PI` はそれを超えうる。IHE の v2.5.1 の表は 250
- 患者 ID の長さは ADR-0003 のとおり、LO の 64 文字まで受け付ける
