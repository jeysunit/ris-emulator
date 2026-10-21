# ADR-0001: MWL の SCP を pynetdicom で自前で持つ

## ステータス

**Accepted** - 2026-10-21

## 背景

dicom-test-generator（以下 DTG）は、モダリティとして MWL（Modality
Worklist）の SCU でワークリストを取得し、予約の内容で画像を作って PACS へ送る。
その試験には、予約を作って MWL で返す RIS の側が要る。

手元で MWL を返す方法は、次の3つがある。

| 方法 | 予約の作り方 | 状態の管理 | 試験での扱いやすさ |
|------|--------------|------------|--------------------|
| Orthanc の Worklists プラグイン | `.wl` ファイルを置く | 無い（ファイルの有無だけ） | 予約を作る別の仕組みが要る |
| DCMTK の `wlmscpfs` | `.wl` ファイルを置く | 無い | 同上。照合の細部を変えられない |
| pynetdicom で自前の SCP | 同じプロセスの中で作る | 予約の状態（予定・実施中・完了・取消）を持てる | 予約の作成・一覧・状態と同じ保存先を使える |

## 決定

1. **MWL の SCP は pynetdicom で自前で持つ。** 理由：予約の作成と状態の
   管理と MWL の応答を、1つの保存先（ADR-0002）で一致させられる。
   ファイルを置く方式では、状態（完了・取消を返さない）を表せない
2. 照合と応答の組み立ては Core の Pure な処理（`app/core/matching.py`・
   `app/core/mwl_dataset.py`）に置き、pynetdicom には C-FIND の受け口
   （`app/mwl/server.py`）だけを持たせる。照合は通信なしで試験できる
3. 照合は DICOM PS3.4 C.2.2.2 に従う。PN は大文字と小文字を区別せず、
   英字・漢字・かなのコンポーネントグループごとに比べる（spec/02_mwl_scp.md 3 章）
4. 応答には要求にあった属性だけを入れる（PS3.4 K.4.1.1.3.2）
5. 応答の文字コードは予約ごとに `ISO_IR 192`・`\ISO 2022 IR 87`・
   `ISO 2022 IR 13\ISO 2022 IR 87` から選ぶ。DTG の画像の文字コードの
   選択（DTG の spec/12 7.1）と同じ3つにそろえ、DTG の `auto` を試せるようにする。
   選んだ文字コードで書けない字（JIS X 0208 に無い字など）があれば、
   pydicom が黙って `?` にするので、予約を作るときに断る

## MPPS は次の段にする

MPPS（N-CREATE・N-SET を受けて予約の状態を進める）は、この段では作らない。
理由：最初の段の目的は「予約を作って MWL に載せる」で、状態は画面と CLI で
手で変えられれば DTG の試験が進む。

次の段の設計の要点だけを残す（作るときに spec に書き起こす）。

- 同じ `MwlServer` に Modality Performed Procedure Step SOP Class
  （1.2.840.10008.3.1.2.3.3）の SCP を足す（`evt.EVT_N_CREATE`・`evt.EVT_N_SET`）
- N-CREATE（IN PROGRESS）で、Scheduled Step Attributes Sequence の
  Accession Number・Scheduled Procedure Step ID で予約を探し、
  状態を「実施中」にする。予約が無い（緊急の患者）ときは、MPPS だけを残す
- N-SET（COMPLETED・DISCONTINUED）で「完了」「取消」にする
- MPPS の SOP Instance UID と受けた属性は、予約とは別の表に残す
- 相手から来る値は信用しない（長さ・形・状態の遷移を確かめる）

## 出典（2026-10-21 に確かめた）

- DICOM PS3.4 K.6 SOP Class Definitions（Table K.6-1 Modality Worklist の属性、
  K.6.1.3.2 SCP Conformance）
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part04/sect_K.6.html>
- DICOM PS3.4 K.4（K.4.1.1.3.2 Response Identifier Structure、
  K.4.1.3 C-FIND SCP Behavior、Table K.4-1 状態の値）
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part04/sect_K.4.html>
- DICOM PS3.4 C.2.2.2 Attribute Matching
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part04/sect_C.2.2.2.html>
- pynetdicom 3.0.4 Basic Worklist Management Service Examples
  <https://pydicom.github.io/pynetdicom/stable/examples/basic_worklist.html>
- pynetdicom 3.0.4 Query/Retrieve (Find) Service Examples（SCP の handler の形）
  <https://pydicom.github.io/pynetdicom/stable/examples/qr_find.html>

## 結果

- Orthanc や DCMTK を足さずに、`python -m app.web` の1つのプロセスで
  予約の作成から MWL の応答までが動く
- 照合の細部（PN のコンポーネントグループ、日付と時刻の期間）は自前の実装なので、
  試験（`tests/core/test_matching.py`）で決まりを固定する
