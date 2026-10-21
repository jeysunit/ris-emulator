# ADR-0005: 発番の出どころ（Issuer）を既定で返す

- 状態：採用
- 日付：2026-10-21

## 背景

DICOM には、識別子をどこが発番したかを示す属性がある。Issuer of Patient ID
(0010,0021) と、Issuer of Accession Number Sequence (0008,0051) の
Local Namespace Entity ID である。PS3.4 Table K.6-1 では、どちらも
Return Key Type 3（返さなくてよい）。

一方、複数の RIS や病院の ID が混ざる試験では、Patient ID が重なることがある。
IHE RAD TF-2 は、HL7 v2 の PID-3 に Assigning Authority の namespace ID を
必ず入れることを求めている。

## 決定

1. **Issuer of Patient ID と Issuer of Accession Number Sequence を、既定で
   `RIS_EMU` にして返す。** 理由：Patient ID が重なる試験を作れるようにする。
   値は HL7 v2 の PID-3・IPC-1 の namespace ID に当たる
2. 値は設定の `orders.issuer_namespace` で変える。英数字と `_` で 16 字までに限る
3. `issuer_namespace: ""` にすれば返さない。Issuer of Patient ID は空、
   Issuer of Accession Number Sequence は項目なしで返す
4. Universal Entity ID（OID など）は持たない

## 検討した選択肢

| 案 | 採らなかった理由 |
|----|------------------|
| 返さない（Return Key Type 3 なので規格には合う） | Patient ID が重なる試験を作れない |
| Universal Entity ID まで持つ | 使う人ごとに OID などを用意させることになる。namespace ID だけで、重なる ID の試験は作れる |

## 結果

- IHE の Enterprise Identity Option（RAD TF-2 4.4.4.1.2.2.9。IPC-1 の universal ID と
  universal ID type まで求める）には足りない
- FHIR の `Identifier.system` に写すときは、使う側が namespace から URI を決める
  （例 `urn:oid:<自分の OID>`、または URL）

## 出典

規格の節番号と URL は [spec/04_identifiers.md](../spec/04_identifiers.md) の
「原典」の節にまとめている。

## 関連

- [spec/02_mwl_scp.md](../spec/02_mwl_scp.md) の 4.1（返す属性）
- [spec/03_web_cli.md](../spec/03_web_cli.md) の 4 章（設定）
