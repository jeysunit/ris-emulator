# ADR-0007: MPPS を受けて予約の状態を進め、DISCONTINUED は「中止」にする

- 状態：採用
- 作成日：2026-10-23
- 最終更新日：2026-10-23

## 背景

ADR-0001 は MPPS を最初の版では作らず、次に作るときの設計の要点を「MPPS は次に作る」の
節に残した。その要点では、N-SET の DISCONTINUED で予約を「取消」にするとしていた。

その後、予約の状態の遷移を表で定め、完了・取消を終わりの状態にした
（spec/01_orders.md の 5 章）。取消は、撮影を始める前に検査そのものを取り消す操作である。
一方、MPPS の DISCONTINUED は、始めた撮影が「取り消された、または正常に終わらなかった」
ことを表す（PS3.3 C.4.14）。2つを同じ状態にすると、撮影を始めたかどうかが予約の状態から
分からなくなる。

## 決定

1. **MPPS の SCP を、MWL と同じ AE タイトル・ポートで受ける。** 理由：モダリティの設定では
   MWL と MPPS の送り先を同じにすることが多い。AE を分けると試験の環境の設定が増える
2. **予約の状態に「中止」（`discontinued`）を足し、MPPS の DISCONTINUED は中止にする。**
   ADR-0001 の「取消にする」を置き換える。中止は終わりの状態で、実施中からだけ変更できる。
   HL7 v2 の Table 0038 Order Status でも、DC（中止）は CA（取消）と別の値である
3. 予約は Scheduled Step Attributes Sequence の Accession Number と Scheduled Procedure
   Step ID の両方で探す。どちらもこの RIS が発番して MWL で返した値。Study Instance UID は、
   自分で発番し直すモダリティがあるので使わない
4. MPPS の記録と予約の状態の変更は、1つのトランザクションで行う。片方だけが書かれると、
   MPPS が COMPLETED なのに予約が実施中のまま、という食い違いが残る
5. 終わりの状態の予約に MPPS が届いても、MPPS を断らずに記録し、予約は変えない。
   PS3.4 F.7.2.1.3 は、予約の状態を理由に SCP が N-CREATE を断ることを定めていない。
   断るとモダリティ側に送信のエラーが残り、撮影の記録も失われる

## 検討した選択肢

- DISCONTINUED を取消にする（ADR-0001 の要点のまま）：撮影を始める前の取り消しと、
  始めた撮影の中止が区別できないので採用しない
- DISCONTINUED の予約を予定に戻し、同じ予約で撮り直せるようにする：終わりの状態を
  戻すと、完了・取消を終わりの状態にした理由（同じ Study Instance UID で2回撮影できる）と
  食い違うので採用しない。撮り直しの扱いは別に決める
- 終わりの状態の予約への MPPS を 0110H で断る：上の決定 5 の理由で採用しない

## 結果

- モダリティの MPPS の送信を、RIS の画面の状態の変化で確かめられる
- 中止の予約は MWL で返らない。中止から戻せないので、撮り直しには新しい予約が要る
- 1つの予約に MPPS が2つあり、1つ目が COMPLETED になると、2つ目が IN PROGRESS でも
  予約は完了になる。予約の詳細に MPPS の一覧を出して、食い違いを見えるようにする

## 決めないこと

- MPPS の N-GET・N-EVENT-REPORT、PACS などへの MPPS の転送
- 予定の無い撮影の MPPS から予約を作ること

## 出典（2026-10-23 に確認）

- DICOM PS3.4 F.7.2 Operations（F.7.2.1.3、F.7.2.2.2、F.7.2.2.3、Table F.7.2-1、
  Table F.7.2-2）
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part04/sect_F.7.2.html>
- DICOM PS3.3 C.4.14 Performed Procedure Step Information Module
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.4.14.html>
- DICOM PS3.7 C.5（0106H・0110H・0111H・0112H）と 10.1.5.1.4 Affected SOP Instance UID
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part07/chapter_C.html>
- HL7 v2 Table 0038 Order Status

## 関連

- ADR-0001（「MPPS は次に作る」の節を、この ADR で置き換える）
- [spec/05_mpps_scp.md](../spec/05_mpps_scp.md)
- [spec/01_orders.md](../spec/01_orders.md) の 5 章
