# ADR-0012: 照合の後の撮影は Study Instance UID と患者ID で照合済みの予約に結び、取消・中止は手の操作のときだけ ORM で知らせる

- 状態：採用
- 作成日：2026-10-25
- 最終更新日：2026-10-25

## 背景

照合（[ADR-0011](0011-reconciliation-links-the-mpps.md)）の後も、モダリティが
仮の患者のまま、同じ Study で撮り続けることがある（IHE PIR の Case 6）。この撮影の
MPPS は受付番号が空なので、今までの結び付け（受付番号と Scheduled Procedure Step ID の
一致）では予約に結び付かず、未照合の一覧に残る。

また、照合で作った予約は PACS に ORM の NW で知らせている。この予約を後で取消・中止
しても、PACS には知らせていなかった。IHE は、手続きの取消・中止・変更を
Procedure Update [RAD-13] の ORM（ORC-1 が CA・DC・XO）で知らせるとしている。

決めることは 3 つあった。照合の後の撮影をどの予約に結ぶか。取消・中止をどの予約に、
どの操作のときに知らせるか。XO をいつ送るか。

## 決定

1. **受付番号が空の項目は、Study Instance UID が一致する「照合で作った予約」に結ぶ。**
   ただし、MPPS の Patient ID が、その照合の仮の患者ID か、予約の正式な患者ID の
   どちらかと一致するときだけにする。Study Instance UID は別の撮影と重ならない前提だが、
   患者ID も確かめれば、UID を取り違えた MPPS を別の患者の予約に結ぶことを防げる。
   照合で作っていない予約は相手にしない（ふつうの予約の撮影は受付番号で結ばれる）
2. **受付番号が入っている項目は、今までどおり受付番号と Scheduled Procedure Step ID
   だけで結ぶ。** 一致しなければ、Study Instance UID が照合済みの予約と同じでも結ばない
3. **照合で作った予約を画面・CLI で取消・中止したら、ORM の CA・DC を照合の記録に足して
   送る。** 状態の変更と通の追加は 1 つのトランザクションで行う。送る順と再送信は
   照合の送信と同じ規則に従う（受理されなかった通で止める）。NW が受理される前に
   CA・DC を送らないため
4. **MPPS（N-SET の DISCONTINUED）による中止では送らない。** モダリティの MPPS は
   PACS も受けるので、PACS は撮影の中止を MPPS から知ることができる
5. **照合で作っていない予約には送らない。** ris-emulator は、ふつうの予約を HL7 で
   PACS に知らせていない。知らせていない予約の取消を送ると、受け手は対象の無い
   メッセージを受けることになる
6. **XO は CLI の `pir send --order-control XO` だけで送る。** ris-emulator には、
   作った予約の中身を後から変える操作が無く、自動で XO を送る場面が無い。受け手の
   試験のために、手で送れるようにだけする

## 検討した選択肢

| 案 | 採らなかった理由 |
|----|------------------|
| 照合の後の撮影を、Study Instance UID だけで結ぶ | UID を取り違えた MPPS を、別の患者の予約に結ぶおそれがある |
| 照合の後の撮影も未照合に残し、人がもう一度照合する | 同じ Study に 2 つめの予約ができ、Study Instance UID が 2 つの予約で重なる |
| すべての予約の取消・中止で ORM を送る | 知らせていない予約の取消になる。宛先の無い一式では、取消のたびに送信失敗が残る |
| MPPS の DISCONTINUED でも DC を送る | PACS は MPPS で中止を知る。MPPS の処理の中で HL7 を送ると、MPPS の応答が送信の時間切れまで遅れる |

## 結果

- 照合の後の撮影の MPPS は、照合で作った予約の詳細に並ぶ。予約が完了なら、
  N-CREATE で実施中には戻らない（[ADR-0007](0007-mpps-advances-order-status.md) の規則）
- 照合で作った予約の詳細の「HL7 送信」の表に、取消・中止の ORM の行が足される
- CLI の `status` は、ORM を送ったときに HL7 の結果で終了コードを返す（拒否は 5、
  失敗は 6）

## 見直す条件

- ふつうの予約も HL7 で PACS に知らせるようにする
- 予約の中身を後から変える操作を足す（XO を自動で送る場面ができる）

## 出典

- IHE Radiology Technical Framework Rev. 23.0：Volume 1 の 4.4.6（Case 6）、
  Volume 2 の 4.13（Procedure Update）
  <https://www.ihe.net/uploadedFiles/Documents/Radiology/IHE_RAD_TF_Vol2.pdf>

## 関連

- [spec/05_mpps_scp.md](../spec/05_mpps_scp.md)
- [spec/06_hl7_pir.md](../spec/06_hl7_pir.md)
- [spec/07_reconciliation.md](../spec/07_reconciliation.md)
- [ADR-0011](0011-reconciliation-links-the-mpps.md)
