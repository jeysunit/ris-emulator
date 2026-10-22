# Tasks

## 1. 台帳の設定

- [ ] 1.1 `app/services/config.py` に装置のモデル（`name`・`ae_title`・`station_name`）と `ModalityCatalog.stations` を足し、AE・SH・名前の長さと重なりの検証を `tests/services/` の試験で確かめる
- [ ] 1.2 古いキー（`station_ae_titles`・モダリティの直下の `station_name`）がある設定を、`stations` の形を示すエラーで断ることを試験で確かめる
- [ ] 1.3 `config/app_config.yaml` の6つのモダリティを `stations` の形にし、`python -m app.cli list` が設定のエラー無しで動くことを確かめる

## 2. 予約の作成

- [ ] 2.1 `Order` に `scheduled_station_label` を足し、`OrderRequest` の `station_ae_title` を `stations`（モダリティ → 名前）に替え、選んだ装置の値と、選ばないときの順番の使い方を `tests/services/test_order_service.py` で確かめる（予定の AE タイトルの今の試験は、装置の選択の試験に書き換える）
- [ ] 2.2 台帳に無い名前・別のモダリティの装置・件数の無いモダリティの装置を `ValidationError` にすることを試験で確かめる
- [ ] 2.3 `app/core/mwl_dataset.py` の Scheduled Procedure Step の項目に、装置の AE タイトル・装置名・モダリティが入ることを `tests/core/test_mwl_dataset.py` と `tests/mwl/test_server.py`（Scheduled Station AE Title で絞り込む C-FIND）で確かめる

## 3. CLI と画面

- [ ] 3.1 CLI の `create` の `--station-ae` を、繰り返して指定できる `--station` に替え、spec のシナリオ（2つのモダリティ・台帳に無い名前）を `tests/cli/test_cli.py` で確かめる
- [ ] 3.2 `new_order.html` の予定の AE タイトルの欄を、モダリティごとの装置の選択（既定は「順に使う」）に替え、別のモダリティの装置が送られたら 400 になることを `tests/web/test_web.py` で確かめる
- [ ] 3.3 一覧と詳細に装置の名前を出し、名前を持たない予約では AE タイトルを出すことを `tests/web/test_web.py` で確かめる

## 4. ドキュメントと全体の確かめ

- [ ] 4.1 `docs/spec/01_orders.md` の 1 章、`docs/spec/03_web_cli.md` の 2〜4 章、`docs/usage.md`（古い設定の書き換えの例）、`docs/project_charter.md` の範囲を直し、markdownlint が合格することを確かめる
- [ ] 4.2 `python -m pytest -q` がすべて合格し、Docker のイメージ（既定の設定）で予約の作成と C-FIND が動くことを確かめる

## Workflow follow-up

- PR のレビューの後に、この change を archive する
