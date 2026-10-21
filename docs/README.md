# ドキュメントの索引

- 作成日：2026-10-22
- 最終更新日：2026-10-22

ris-emulator のドキュメントはこのディレクトリにあります。使い方はルートの
[README](../README.md) を参照してください。ここには、設計を知りたい人と、
変更したい人のためのドキュメントを置いています。

## ドキュメントの種類

| 種類 | 内容 | 更新の規則 |
|------|------|------------|
| [project_charter.md](project_charter.md) | 目的、範囲、規格に違反しないという前提 | 目的や範囲が変わるときだけ更新する |
| [architecture.md](architecture.md) | プロセス、層、ディレクトリ | 構成が変わったら更新する |
| [spec/](spec/) | 現在の動作。規格の節番号を出典として書く | コードと同じ PR で更新し、常に現在の動作に合わせる |
| [decisions/](decisions/README.md) | 設計判断の理由（ADR） | 採用後は本文を書き換えない。判断を変えるときは新しい ADR を作成する |
| [roadmap.md](roadmap.md) | 未実装の機能 | 実装したら spec に移して削除する |
| [development.md](development.md) | 開発環境、テスト、変更の手順 | 手順が変わったら更新する |

### 冒頭の日付

ADR 以外のドキュメント（ルートの README と、docs/ の下のドキュメント）は、
タイトルの直後に次の2行を書きます。ファイルを Git の外にコピーして渡したときにも、
いつ時点の内容かが分かるようにするためです。

```markdown
- 作成日：YYYY-MM-DD
- 最終更新日：YYYY-MM-DD
```

- 作成日は、ファイルを作成した日です。別のドキュメントから分割して作成したときは、
  元のドキュメントの作成日にします
- 最終更新日は、内容を更新した日です。記入漏れは
  `scripts/check_doc_dates.py` で検出します（[development.md](development.md) の 3 章）

ADR には「状態」「日付」「作成日」の3行を書きます（[decisions/README.md](decisions/README.md)）。

## spec

| ファイル | 内容 |
|----------|------|
| [01_orders.md](spec/01_orders.md) | 予約の項目、番号の採番、患者の生成、予定日時、状態 |
| [02_mwl_scp.md](spec/02_mwl_scp.md) | MWL の SCP：応答の流れ、照合、返す属性、文字コード |
| [03_web_cli.md](spec/03_web_cli.md) | Web 画面・CLI・設定・Docker |
| [04_identifiers.md](spec/04_identifiers.md) | 発番する識別子と、DICOM・HL7 v2・FHIR R5 の規則との対応 |

## decisions

ADR の一覧と書き方は [decisions/README.md](decisions/README.md) にあります。

## 食い違いを見つけたとき

spec とコードが食い違っていたら、どちらが正しいかを確認し、誤っている側を
修正してください。ルートの README と docs が食い違っていたら、docs を正とします。
