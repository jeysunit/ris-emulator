# 設計の判断（ADR）

ADR（Architecture Decision Record）は、なぜその設計にしたかを1件ずつ残す記録です。
今どう動くかは [spec](../spec/) に書き、ここには判断と理由だけを書きます。

## 一覧

| 番号 | 題 | 状態 |
|------|----|------|
| [0001](0001-mwl-scp-with-pynetdicom.md) | MWL の SCP を pynetdicom で自前で持つ | 採用 |
| [0002](0002-sqlite-order-store.md) | 予約の保存は SQLite にする | 採用 |
| [0003](0003-identifiers-fit-dicom-and-hl7.md) | 発番する識別子は DICOM・HL7 v2・FHIR R5 にそのまま入る形に絞る | 採用 |
| [0004](0004-ris-issues-study-instance-uid.md) | Study Instance UID は予約を作るときに RIS が発番する | 採用 |
| [0005](0005-return-issuer-namespace.md) | 発番の出どころ（Issuer）を既定で返す | 採用 |
| [0006](0006-web-ui-loopback-by-default.md) | Web 画面は既定でループバックだけで待ち受け、それ以外のアドレスでは認証を必須にする | 採用 |

## 書き方

- 新しい ADR は [template.md](template.md) を写して書きます。ファイル名は
  `NNNN-英語の-kebab-case.md` で、番号は続きから振ります
- 冒頭は「状態」と「日付」の2行だけにします。状態は 提案・採用・廃止・
  置き換え済み（ADR-NNNN）のどれかです
- 必須の節は 背景・決定・検討した選択肢・結果 です。決めないこと・
  見直す条件・出典・関連は、要るときだけ書きます
- 採用した ADR の本文は書き換えません。判断を変えるときは新しい ADR を起こし、
  古い ADR の状態の行を「置き換え済み（ADR-NNNN）」に直します
- ADR を足したら、この一覧に1行足します
