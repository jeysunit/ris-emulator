# 目的と範囲

このドキュメントは、ris-emulator の目的と、対象外とするものを定める。
現在の動作は [spec](spec/) に、設計判断の理由は [decisions](decisions/) に書く。

## 1. 目的

開発・テストの環境で RIS の役割を担う。架空の患者と検査の予約を作成し、
MWL（Modality Worklist、C-FIND の SCP）で返す。モダリティがワークリストを取得し、
撮影して PACS へ送信する流れのうち、予約の作成とワークリストの応答を担当する。

## 2. 範囲

対象とするもの：

- 予約の作成（CLI と Web 画面）。「CT を 3 件、MR を 1 件」のように指定する
- 患者は乱数で生成するか、名簿（YAML）から選ぶ。氏名は英字・漢字・カナの
  3つのコンポーネントグループで保持する
- 受付番号・Requested Procedure ID・Scheduled Procedure Step ID・
  Study Instance UID・予定日時・装置（予定の AEタイトルと装置名）・検査名・依頼科の設定。
  装置は設定ファイルの台帳から名前で選ぶ
- MWL の SCP。C-FIND に、予定の AEタイトル・日付の範囲・モダリティ・患者ID・
  氏名・受付番号などで絞り込んで応答する
- 応答の文字コードを `ISO_IR 192`・`\ISO 2022 IR 87`・
  `ISO 2022 IR 13\ISO 2022 IR 87` から予約ごとに選ぶ
- 予約の一覧と状態（予定・実施中・完了・取消・中止）の Web 画面での確認と、手動での
  変更。完了・取消・中止の予約は MWL で返さない
- MPPS の SCP。モダリティの N-CREATE・N-SET を受け、予約を実施中・完了・中止にする
- 撮り直しの扱いの選択（同じ予約の中で追加するか、撮り直しの予約を作るか）
- HL7 v2 の送信。PIR（Patient Information Reconciliation）の Patient Update
  （ADT^A08・ADT^A40）、Procedure Scheduled（ORM^O01 の NW）、Procedure Update
  （ORM^O01 の CA・DC・XO）を組み立て、MLLP で設定した宛先へ
  送り、ACK を受け取る。PACS の PIR への対応を試す相手にするためで、宛先は
  開発・試験の環境の受け口に限る
- 照合。予約の無い撮影（MPPS だけが記録された撮影）に、正式な患者と新しい予約を結び、
  結果を HL7 v2 で送る。送信の結果の記録と、再送信を含む。照合の後に同じ Study で
  届く撮影をその予約に結ぶことと、照合で作った予約の取消・中止を知らせることを含む
- Docker イメージ

対象外とするもの：

- HL7 の受信
- Patient Demographics・帳票
- 実在の患者のデータ。医療機関の RIS・PACS・モダリティへの接続

未実装の機能は [roadmap.md](roadmap.md) にある。

## 3. 前提：DICOM と HL7 に違反しない

ris-emulator が返す値と動作は、DICOM と HL7（v2・FHIR）の規則に違反しない。
これは開発の前提であり、ほかの都合より優先する。

規格への準拠をドキュメントにどう書くかは、[README.md の「書き方」](README.md#書き方)
に従う。
