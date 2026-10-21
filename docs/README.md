# ドキュメントの索引

- 作成日：2026-10-22
- 最終更新日：2026-10-22

ris-emulator のドキュメントはこのディレクトリにあります。使い方はルートの
[README](../README.md) を参照してください。ここには、設計を知りたい人と、
変更したい人のためのドキュメントを置いています。

## 索引

| ドキュメント | 内容 |
|--------------|------|
| [project_charter.md](project_charter.md) | 目的、範囲、規格に違反しないという前提 |
| [architecture.md](architecture.md) | プロセス、層、ディレクトリ |
| [spec/](#spec) | 現在の動作 |
| [decisions/](decisions/README.md) | 設計判断とその理由（ADR） |
| [roadmap.md](roadmap.md) | 未実装の機能 |
| [development.md](development.md) | 開発環境、テスト、変更の手順 |

### spec

| ファイル | 内容 |
|----------|------|
| [01_orders.md](spec/01_orders.md) | 予約の項目、番号の採番、患者の生成、予定日時、状態 |
| [02_mwl_scp.md](spec/02_mwl_scp.md) | MWL の SCP：応答の流れ、照合、返す属性、文字コード |
| [03_web_cli.md](spec/03_web_cli.md) | Web 画面・CLI・設定・Docker |
| [04_identifiers.md](spec/04_identifiers.md) | 発番する識別子と、DICOM・HL7 v2・FHIR R5 の規則との対応 |

### decisions

ADR の一覧と、ADR に固有の書き方は [decisions/README.md](decisions/README.md) にあります。

## 書き方

- ADR 以外のドキュメント（ルートの README と、docs/ の下のドキュメント）は、
  タイトルの直後に `- 作成日：YYYY-MM-DD` と `- 最終更新日：YYYY-MM-DD` の2行を書きます。
  ファイルを Git の外にコピーして渡したときにも、いつ時点の内容かが分かるようにするためです
- 作成日は、ファイルを作成した日です。別のドキュメントから分割して作成したときは、
  元のドキュメントの作成日にします
- 最終更新日は、内容を更新した日です。記入漏れは `scripts/check_doc_dates.py` で
  検出します（[development.md](development.md) の 3 章）
- spec には現在の動作を書きます。コードと同じ PR で更新し、常に現在の動作に合わせます
- 規格に従って実装した箇所は、spec に規格の節番号を書きます（例 PS3.4 C.2.2.2、PS3.5 9.1）
- 規格が複数の形式を許すときは、どれを選んだかを spec に書き、選んだ理由を ADR に書きます
- 規格で確認していないことは、未確認であると spec に書きます
- 設計判断の理由は ADR に書きます。ADR の書き方は [decisions/README.md](decisions/README.md) に従います
- roadmap.md には未実装の機能だけを書きます。実装したら spec に移し、roadmap.md から削除します
- project_charter.md は目的や範囲が変わるときだけ、architecture.md は構成が変わったとき、
  development.md は手順が変わったときに更新します
- 言葉は、読み手が普段使う言葉で書きます。エンジニアが普通に使う専門用語は、
  和語に言い換えずにそのまま使います
- spec とコードが食い違っていたら、どちらが正しいかを確認し、誤っている側を修正します
- ルートの README と docs が食い違っていたら、docs を正とします
