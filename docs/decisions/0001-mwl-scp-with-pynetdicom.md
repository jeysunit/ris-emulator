# ADR-0001: MWL の SCP を pynetdicom で自前で実装する

- 状態：採用（「MPPS は次に作る」の節は ADR-0007 で置き換え済み）
- 作成日：2026-10-21
- 最終更新日：2026-10-23

## 背景

モダリティは、MWL（Modality Worklist）の SCU でワークリストを取得し、
予約の内容で画像を生成して PACS へ送信する。そのテストには、予約を作成して MWL で返す
RIS 側が必要になる。

ローカルで MWL を返す方法は、次の3つがある。

| 方法 | 予約の作成方法 | 状態の管理 | テストでの扱いやすさ |
|------|----------------|------------|----------------------|
| Orthanc の Worklists プラグイン | `.wl` ファイルを配置する | 無い（ファイルの有無だけ） | 予約を作成する別の仕組みが必要 |
| DCMTK の `wlmscpfs` | `.wl` ファイルを配置する | 無い | 同上。照合の細部を変更できない |
| pynetdicom で自前の SCP | 同じプロセスの中で作成する | 予約の状態（予定・実施中・完了・取消）を保持できる | 予約の作成・一覧・状態と同じ保存先を使える |

## 決定

1. **MWL の SCP は pynetdicom で自前で実装する。** 理由：予約の作成と状態の
   管理と MWL の応答を、1つの保存先（ADR-0002）で一致させられる。
   ファイルを配置する方式では、状態（完了・取消を返さない）を表現できない
2. 照合と応答の組み立ては Core の Pure な処理（`app/core/matching.py`・
   `app/core/mwl_dataset.py`）に置き、pynetdicom には C-FIND のハンドラー
   （`app/mwl/server.py`）だけを持たせる。照合は通信なしでテストできる
3. 照合は DICOM PS3.4 C.2.2.2 に従う。PN は大文字と小文字を区別せず、
   英字・漢字・かなのコンポーネントグループごとに比較する（spec/02_mwl_scp.md 3 章）
4. 応答には要求にあった属性だけを含める（PS3.4 K.4.1.1.3.2）
5. 応答の文字コードは予約ごとに `ISO_IR 192`・`\ISO 2022 IR 87`・
   `ISO 2022 IR 13\ISO 2022 IR 87` から選ぶ。
   選んだ文字コードで表せない文字（JIS X 0208 に無い文字など）があれば、
   pydicom が `?` に置き換えるので、予約の作成時にエラーにする

## MPPS は次に作る

MPPS（N-CREATE・N-SET を受けて予約の状態を進める）は、最初の版では作らない。
理由：最初の版の目的は「予約を作成して MWL で返す」で、状態は画面と CLI で
手動で変更できればモダリティのテストが進む。

次に作るときの設計の要点だけを残す（実装するときに spec を作成する）。

- 同じ `MwlServer` に Modality Performed Procedure Step SOP Class
  （1.2.840.10008.3.1.2.3.3）の SCP を追加する（`evt.EVT_N_CREATE`・`evt.EVT_N_SET`）
- N-CREATE（IN PROGRESS）で、Scheduled Step Attributes Sequence の
  Accession Number・Scheduled Procedure Step ID で予約を検索し、
  状態を「実施中」にする。予約が無い（緊急の患者）ときは、MPPS だけを記録する
- N-SET（COMPLETED・DISCONTINUED）で「完了」「取消」にする
- MPPS の SOP Instance UID と受信した属性は、予約とは別のテーブルに記録する
- 相手から受信した値は信用しない（長さ・形式・状態の遷移を検証する）

## 出典（2026-10-21 に確認）

- DICOM PS3.4 K.6 SOP Class Definitions（Table K.6-1 Modality Worklist の属性、
  K.6.1.3.2 SCP Conformance）
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part04/sect_K.6.html>
- DICOM PS3.4 K.4（K.4.1.1.3.2 Response Identifier Structure、
  K.4.1.3 C-FIND SCP Behavior、Table K.4-1 ステータスの値）
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part04/sect_K.4.html>
- DICOM PS3.4 C.2.2.2 Attribute Matching
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part04/sect_C.2.2.2.html>
- pynetdicom 3.0.4 Basic Worklist Management Service Examples
  <https://pydicom.github.io/pynetdicom/stable/examples/basic_worklist.html>
- pynetdicom 3.0.4 Query/Retrieve (Find) Service Examples（SCP の handler の形）
  <https://pydicom.github.io/pynetdicom/stable/examples/qr_find.html>

## 結果

- Orthanc や DCMTK を追加せずに、`python -m app.web` の1つのプロセスで
  予約の作成から MWL の応答までが動作する
- 照合の細部（PN のコンポーネントグループ、日付と時刻の期間）は自前の実装なので、
  テスト（`tests/core/test_matching.py`）で規則を固定する
