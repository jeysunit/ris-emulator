# 目的と範囲

このドキュメントは、ris-emulator の目的と、対象外とするものを定める。
現在の動作は [spec](spec/) に、設計判断の理由は [decisions](decisions/) に書く。

## 1. 目的

開発・テストの環境で RIS の役割を担う。架空の患者と検査の予約を作成し、
MWL（Modality Worklist、C-FIND の SCP）で返す。モダリティがワークリストを取得し、
撮影して PACS へ送信する流れのうち、予約の作成とワークリストの応答を担当する。

## 2. 範囲

対象とするもの：

- 予約の作成（CLI・Web 画面）。一覧の表示と、状態の手動での変更
- MWL の SCP
- Docker イメージ

対象外とするもの：

- HL7 の受信
- Patient Demographics・帳票
- 実在の患者のデータ。医療機関の RIS・PACS・モダリティへの接続

未実装の機能（MPPS など）は [roadmap.md](roadmap.md) にある。

## 3. 前提：DICOM と HL7 に違反しない

ris-emulator が返す値と動作は、DICOM と HL7（v2・FHIR）の規則に違反しない。
これは開発の前提であり、ほかの都合より優先する。

規格への準拠をドキュメントにどう書くかは、[README.md の「書き方」](README.md#書き方)
に従う。
