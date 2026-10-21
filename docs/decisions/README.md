# 設計判断（ADR）

ADR（Architecture Decision Record）の一覧と、ADR に固有の書き方です。
ドキュメントに共通の規則は [docs/README.md の「書き方」](../README.md#書き方) に従います。

## 一覧

| 番号 | タイトル | 状態 |
|------|----------|------|
| [0001](0001-mwl-scp-with-pynetdicom.md) | MWL の SCP を pynetdicom で自前で実装する | 採用 |
| [0002](0002-sqlite-order-store.md) | 予約の保存先は SQLite にする | 採用 |
| [0003](0003-identifiers-fit-dicom-and-hl7.md) | 発番する識別子は DICOM・HL7 v2・FHIR R5 にそのまま入る形式に限定する | 採用 |
| [0004](0004-ris-issues-study-instance-uid.md) | Study Instance UID は予約の作成時に RIS が発番する | 採用 |
| [0005](0005-return-issuer-namespace.md) | 発番元（Issuer）を既定で返す | 採用 |
| [0006](0006-web-ui-loopback-by-default.md) | Web 画面は既定でループバックだけで待ち受け、それ以外のアドレスでは認証を必須にする | 採用 |

## 書き方

- 新しい ADR は [template.md](template.md) をコピーして書きます。ファイル名は
  `NNNN-英語の-kebab-case.md` で、番号は連番にします
- 冒頭は「状態」「日付」「作成日」の3行だけにします。状態は 提案・採用・廃止・
  置き換え済み（ADR-NNNN）のいずれかです。日付は現在の状態になった日、作成日は
  ファイルを作成した日です。ファイルを Git の外にコピーして渡したときにも、
  いつ時点の内容かが分かるようにするためです
- 必須の節は 背景・決定・検討した選択肢・結果 です。決めないこと・
  見直す条件・出典・関連は、必要なときだけ書きます
- 採用した ADR の本文は書き換えません。判断を変えるときは新しい ADR を作成し、
  古い ADR の状態の行を「置き換え済み（ADR-NNNN）」に変更します
- ADR を追加したら、この一覧に1行追加します
