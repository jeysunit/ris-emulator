# ADR-0008: 撮り直しの扱いを設定で選び、既定は IHE の Append Case にする

- 状態：採用
- 作成日：2026-10-23
- 最終更新日：2026-10-23

## 背景

撮影をやり直すときの扱いは、施設によって違う。IHE の Scheduled Workflow は、撮り直しを
同じ予約・同じ Study の中の追加として扱う。施設のローカルルールでは、撮り直しを別の検査として
扱い、受付番号から Study Instance UID まで新しくすることがある。それまでの RIS は前者の形しか
試験できず、後者の施設のモダリティと PACS を試験するには、撮り直しの予約を作れる必要があった。
モダリティの側も同じ考え方の設定を持つ前提で、設定の名前と値をそろえる。

## 決定

1. **設定 `orders.retake_mode` を足し、値は `append` と `new_order` にする。** 値の名前は
   撮り直しの結果を表す。`ihe`・`local` のような出どころの名前は、施設のルールが IHE と同じ
   場合に読み違える
2. **既定は `append` にする。** IHE RAD TF-2 4.6.4.1.2.3.3 Append Case は、SPS と PPS が
   1 対 N の場合で、最初の PPS の後にスケジュールされていない PPS を追加する。理由の例に
   「画質が悪い画像の撮り直し」がある。すべての PPS は同じ Requested Procedure と元の SPS を
   参照する。RIS は何もしなくてよく、MPPS の記録の規則（ADR-0007）だけで動く。既定にすれば、
   設定を変えない利用者の動作も変わらない
3. `append` では、中止の予約に同じ予約の2つ目の MPPS が来ても、予約を実施中に戻さない。
   戻す例外を入れると「終わりの状態の予約には記録だけ」（ADR-0007）と食い違い、終わりの状態の
   意味が場合で変わる。2つ目の MPPS は記録され、予約の詳細で分かる
4. `new_order` では、元の予約を写して番号を新しく発番した撮り直しの予約を作る。元の予約が
   実施中なら中止にし、完了・中止ならそのままにする（下の表の案1）
5. 撮り直しの予約と元の予約の関係（`retake_of`）は RIS の中だけに持ち、MWL には入れない。
   DICOM の MWL には元の予約を表す属性が無い。Reason for the Requested Procedure (0040,1002)
   に書く案は、臨床の理由を書く属性を別の用途に使うので選ばない

## 検討した選択肢

撮り直しの予約を作るときの、元の予約の状態：

| 案 | 元が実施中 | 元が完了・中止 | 採らなかった理由 |
|----|------------|----------------|------------------|
| 1（採用） | 中止にする | そのまま | - |
| 2 | 完了にする | そのまま | 1枚も撮っていない予約まで完了になり、画像の無い完了の予約が残る |
| 3 | そのまま | そのまま | 実施中の予約が MWL に残り、モダリティに元と撮り直しの2件が並ぶ |

案1は、DISCONTINUED の意味（PS3.3 C.4.14 の「取り消された、または正常に終わらなかった」）に
合い、終わりの状態を変えない決まりも破らない。撮った画像が PACS にあるか（完了）無いか
（中止）が状態に残る。

## 結果

- `new_order` の施設のモダリティと PACS を、新しい受付番号・Study Instance UID の撮り直しで
  試験できる
- `append` で、中止の予約を同じ予約の中で撮り直すと、予約は中止のまま残る
- `new_order` で、元の予約の MPPS が撮り直しの後に COMPLETED で届いても、元の予約は中止の
  まま（MPPS は記録されるので、予約の詳細で食い違いが見える）

## 決めないこと

- HL7 v2 で撮り直しの関係を送ること（ORC-8 Parent・OBR-29 Parent の使い方）

## 出典（2026-10-23 に確認）

- IHE Radiology Technical Framework Volume 2（RAD TF-2）Rev. 23.0、
  4.6.4.1.2.3.3 Append Case
  <https://www.ihe.net/uploadedFiles/Documents/Radiology/IHE_RAD_TF_Vol2.pdf>
- IHE RAD TF-2x Appendix A（IHE-A.3.3：Append Case の画像は元の画像の Study Date・
  Study Time・Study Description を使う）
  <https://www.ihe.net/uploadedFiles/Documents/Radiology/IHE_RAD_TF_Vol2x.pdf>
- DICOM PS3.3 C.4.14 Performed Procedure Step Information Module
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.4.14.html>

## 関連

- ADR-0007（MPPS を受けて予約の状態を進める）
- [spec/01_orders.md](../spec/01_orders.md) の 7 章
