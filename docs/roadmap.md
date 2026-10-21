# ロードマップ

- 作成日：2026-10-21
- 最終更新日：2026-10-22

このドキュメントには、未実装の機能を書く。ここに書いた機能は、まだ動作しない。
現在の動作は [spec](spec/) にある。実装した機能は spec に移し、ここから削除する。

## 次に作るもの：MPPS の SCP

MPPS（Modality Performed Procedure Step）の N-CREATE・N-SET を受けて、
予約の状態を進める。現在は、状態を Web 画面と CLI で手動で変更する。

設計の要点は [ADR-0001](decisions/0001-mwl-scp-with-pynetdicom.md) の
「MPPS は次に作る」の節にある。実装するときに spec を作成する。
