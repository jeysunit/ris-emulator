# 文書の索引

ris-emulator の文書はこのディレクトリにあります。使い方はルートの
[README](../README.md) を読んでください。ここには、作りを知りたい人と、
直したい人のための文書を置いています。

## 文書の種類

| 種類 | 何を書くか | 直し方 |
|------|------------|--------|
| [project_charter.md](project_charter.md) | 目的、範囲、規格に違反しないという前提 | 目的や範囲が変わるときだけ直す |
| [architecture.md](architecture.md) | プロセス、層、ディレクトリ | 構成が変わったら直す |
| [spec/](spec/) | 今どう動くか。規格の節番号を出典として書く | コードと同じ PR で直し、いつも今の振る舞いに合わせる |
| [decisions/](decisions/README.md) | なぜそう決めたか（ADR） | 採用した後は本文を書き換えない。判断を変えるときは新しい ADR を起こす |
| [roadmap.md](roadmap.md) | まだ作っていないもの | 作ったら spec に移して消す |
| [development.md](development.md) | 開発の環境、試験、変更の進め方 | 手順が変わったら直す |

## spec

| ファイル | 中身 |
|----------|------|
| [01_orders.md](spec/01_orders.md) | 予約の項目、番号の付け方、患者の作り方、予定の日時、状態 |
| [02_mwl_scp.md](spec/02_mwl_scp.md) | MWL の SCP：応答の流れ、照合、返す属性、文字コード |
| [03_web_cli.md](spec/03_web_cli.md) | Web 画面・CLI・設定・Docker |
| [04_identifiers.md](spec/04_identifiers.md) | 発番する識別子と、DICOM・HL7 v2・FHIR R5 の決まりとの対応 |

## decisions

ADR の一覧と書き方は [decisions/README.md](decisions/README.md) にあります。

## 食い違いを見つけたとき

spec とコードが食い違っていたら、どちらが正しいかを確かめて、間違っている側を
直してください。ルートの README と docs が食い違っていたら、docs が正です。
