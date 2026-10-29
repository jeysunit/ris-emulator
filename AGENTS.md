# AGENTS.md

ris-emulator は、開発・テスト用の RIS エミュレーターです（架空の患者と検査の
予約、MWL・MPPS の SCP、HL7 v2 の送信、Web 画面と CLI）。概要は
[README.md](README.md)、ドキュメントの索引と書き方は [docs/README.md](docs/README.md)
にあります。

## 画面（app/web/）

- **ui-kit の部品と絵で組む。** CSS は `app/web/static/ui-kit/` の
  `tokens.css`・`components.css`、絵は `icons.svg`
  （`<use href="/static/ui-kit/icons.svg#i-…">`）。
- **ui-kit の写しは直さない。** 版は `VERSION`、指紋は `SHA256SUMS`。版が上がった
  ら 5 つのファイルを丸ごと写し直す。写しが指紋と合うことは
  `tests/web/test_ui_kit_copy.py` が確かめる。
- **無い部品・無い絵は作らない。** 製品の中で作り直さず、先に ui-kit を直して
  もらい、写し直してから使う。`app/web/static/app.css` には、この製品にしか無い
  部品の差分だけを書き、ui-kit と同じ名前の部品を定義し直さない。
- 色の値は `tokens.css` だけが持つ。`app.css` に 16 進の色を書かない（試験が
  ある）。
- CSP でインラインのスクリプトと `style` 属性は使えない。小さな動きは
  `app/web/static/app.js` に置く。
- 画面の文言は RIS・PACS で一般的な用語にし、説明文は置かない
  （[docs/spec/03_web_cli.md](docs/spec/03_web_cli.md) の 3.2）。

## 変更の手順

動作を変えるときは、次の順に更新します
（[docs/development.md](docs/development.md) の 4）。

1. spec（`docs/spec/`。画面の要件は `openspec/specs/` も）を直す
2. 設計判断を伴うなら ADR（`docs/decisions/`）を足す
3. コードとテストを直す
4. 使い方が変わるなら `docs/usage.md` を直す

## 試験と検査

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
pytest
npx markdownlint-cli2 "**/*.md" "#.venv" "#.pytest_cache"
python scripts/check_doc_dates.py origin/main..HEAD
```

- 試験の削除・スキップ・期待の緩和をしない。画面の文言を変えたら、その文言を
  見る試験を同じ PR で直す。
- 規格に従う規則（照合・識別子の形式など）は試験で固定する。

## 文書の書き方

- Markdown の本文は 80 文字で折り返す（MD013）。日本語で、読み手が普段使う
  言葉で書く。
- spec には現在の動作だけを書く。設計判断の理由は ADR に書く。roadmap.md には
  未実装のものだけを書く。

## commit と PR

- commit は Conventional Commits（`feat:`・`fix:`・`docs:`・`test:`・`chore:`、
  題は日本語）。
- 公開のリポジトリなので、commit に `Claude-Session` の行を入れない
  （`Co-Authored-By` だけ）。非公開の場所の名前・URL も書かない。
- PR の本文は日本語。変えたこと・確かめたこと（試験の結果）・残る点を書く。
- 版の正は git のタグ（`vX.Y.Z`）。コードの中に版の定数を持たない
  （[docs/development.md](docs/development.md) の 6）。
