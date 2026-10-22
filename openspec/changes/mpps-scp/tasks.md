# Tasks

## 1. 中止の状態

- [ ] 1.1 `order-status-transitions` が archive 済みで、`openspec/specs/order-status/spec.md` があることを確かめる
- [ ] 1.2 `OrderStatus` に `discontinued`（中止）を足し、`ALLOWED_TRANSITIONS` を spec の表にし、25 通りの組み合わせを `tests/core/` の試験で確かめる
- [ ] 1.3 `mwl.statuses` に `discontinued` を書いた設定を断り、CLI の `status` と画面の選択肢で中止を扱えることを `tests/services/`・`tests/cli/`・`tests/web/` の試験で確かめる

## 2. MPPS の記録

- [ ] 2.1 `OrderStore` に `mpps` の表と、MPPS の記録と予約の状態の変更を1つのトランザクションで行う処理を足し、途中で失敗したらどちらも書かれないことを `tests/services/` の試験で確かめる
- [ ] 2.2 Accession Number と Scheduled Procedure Step ID の両方で予約を探し、片方だけ一致する予約は結び付けないことを試験で確かめる

## 3. MPPS の SCP

- [ ] 3.1 `MwlServer` に MPPS の Presentation Context と N-CREATE の handler を足し、spec の N-CREATE のシナリオ（実施中になる・2件・予定の無い撮影・COMPLETED で 0106H・重なりで 0111H・取消の予約）を、pynetdicom の SCU から送る `tests/mwl/` の試験で確かめる
- [ ] 3.2 N-SET の handler を足し、完了・中止の反映、知らない UID で 0112H、終わった MPPS で 0110H と Error ID A710 を `tests/mwl/` の試験で確かめる
- [ ] 3.3 SOP Instance UID の無い N-CREATE で SCP が発番することを PS3.7 の N-CREATE の節で確かめてから実装し、応答の Affected SOP Instance UID を試験で確かめる
- [ ] 3.4 不正な値（UID の形・Enumerated Values に無い状態）が 0106H になり、想定外の例外が 0110H になって SCP が止まらないことを試験で確かめる

## 4. 画面とドキュメント

- [ ] 4.1 予約の詳細に、結び付いた MPPS の SOP Instance UID・状態・受けた日時を出すことを `tests/web/test_web.py` で確かめる
- [ ] 4.2 `docs/spec/05_mpps_scp.md` を足し、`docs/spec/01_orders.md` の 5 章・`02_mwl_scp.md` の 1 章・`docs/roadmap.md`・`docs/project_charter.md`・`docs/usage.md` を直し、markdownlint が合格することを確かめる
- [ ] 4.3 ADR「MPPS を受けて予約の状態を進める」を template.md から作り、ADR-0001 の「MPPS は次に作る」の節を置き換えたことを状態の行に書き、`python scripts/check_doc_dates.py origin/main..HEAD` が合格することを確かめる

## 5. 全体の確かめ

- [ ] 5.1 `python -m pytest -q` がすべて合格し、Docker のイメージに、pynetdicom の SCU で C-FIND・N-CREATE・N-SET を順に送り、画面で実施中から完了になることを確かめる

## Workflow follow-up

- PR のレビューの後に、この change を archive する
