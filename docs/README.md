# ドキュメントの索引

ris-emulator の使い方・設計・仕様・開発の手順を書いたドキュメントの索引と、
ドキュメントの書き方です。

## 索引

| ドキュメント | 内容 |
|--------------|------|
| [usage.md](usage.md) | 使い方：起動、設定の変更、モダリティの接続、予約の作成と確認 |
| [project_charter.md](project_charter.md) | 目的、範囲、規格に違反しないという前提 |
| [architecture.md](architecture.md) | プロセス、層、ディレクトリ |
| [spec/01_orders.md](spec/01_orders.md) | 予約の項目、番号の採番、患者の生成、予定日時、状態、撮り直し |
| [spec/02_mwl_scp.md](spec/02_mwl_scp.md) | MWL の SCP：応答の流れ、照合、返す属性、文字コード |
| [spec/03_web_cli.md](spec/03_web_cli.md) | Web 画面・CLI・設定・Docker |
| [spec/04_identifiers.md](spec/04_identifiers.md) | 発番する識別子と、DICOM・HL7 v2・FHIR R5 の規則との対応 |
| [spec/05_mpps_scp.md](spec/05_mpps_scp.md) | MPPS の SCP：N-CREATE・N-SET、予約との結び付け、記録 |
| [spec/06_hl7_pir.md](spec/06_hl7_pir.md) | HL7 v2.3.1 の送信（PIR）：ADT^A40・ADT^A08・ORM^O01 の組み立てと例、MLLP、ACK |
| [decisions/README.md](decisions/README.md) | ADR の一覧と、ADR に固有の書き方 |
| [roadmap.md](roadmap.md) | 未実装の機能 |
| [development.md](development.md) | 開発環境と Python での起動、テスト、確認のスクリプト、変更の手順 |

## 書き方

- spec には現在の動作を書きます。コードと同じ PR で更新し、常に現在の動作に合わせます
- 規格に従って実装した箇所は、spec に規格の節番号を書きます（例 PS3.4 C.2.2.2、PS3.5 9.1）
- 規格が複数の形式を許すときは、どれを選んだかを spec に書き、選んだ理由を ADR に書きます
- 規格で確認していないことは、未確認であると spec に書きます
- 設計判断の理由は ADR に書きます。ADR の書き方は [decisions/README.md](decisions/README.md) に従います
- roadmap.md には未実装の機能だけを書きます。実装したら spec に移し、roadmap.md から削除します
- project_charter.md は目的や範囲が変わるときだけ、architecture.md は構成が変わったとき、
  development.md は手順が変わったときに更新します
- Markdown の本文は 80 文字で折り返します（`.markdownlint-cli2.yaml` の MD013）
- 図の矢印はデータが流れる向きに描き、ラベルには流れるもの（名詞）を書きます。
  要求を送る向きでは描きません
- 言葉は、読み手が普段使う言葉で書きます。エンジニアが普通に使う専門用語は、
  和語に言い換えずにそのまま使います
- spec とコードが食い違っていたら、どちらが正しいかを確認し、誤っている側を修正します
- ルートの README と docs が食い違っていたら、docs を正とします
