# Spec Delta

## ADDED Requirements

### Requirement: 照合の後に同じ Study で届く撮影は照合で作った予約に結ぶ

N-CREATE の Scheduled Step Attributes Sequence の項目の Accession Number が空で、その
Study Instance UID が照合で作った予約と同じで、MPPS の Patient ID がその照合の仮の
患者ID か予約の正式な患者ID と同じなら、MPPS をその予約に結び付けなければならない
（SHALL。IHE PIR の Case 6）。照合で作っていない予約、患者ID の合わない撮影には
結び付けてはならない（SHALL NOT）。

#### Scenario: 仮の患者のまま追加で撮る

- **WHEN** 照合の後に、受付番号が空、同じ Study Instance UID、仮の患者ID の N-CREATE が届く
- **THEN** MPPS は照合で作った予約に結び付き、未照合の一覧に出ない。予約の MPPS は 2 件になる

#### Scenario: 患者ID が違う

- **WHEN** 照合の後に、同じ Study Instance UID で、仮とも正式とも違う患者ID の N-CREATE が届く
- **THEN** MPPS はどの予約にも結び付かず、未照合の一覧に出る

#### Scenario: 完了の予約

- **WHEN** 完了の予約に、照合の後の撮影の N-CREATE（IN PROGRESS）が届く
- **THEN** MPPS は結び付き、予約は完了のまま

### Requirement: 照合で作った予約の取消・中止を ORM で知らせる

照合で作った予約を画面か CLI で取消にしたら ORM^O01（ORC-1 が `CA`）、中止にしたら
ORM^O01（ORC-1 が `DC`）を、照合の記録の送信の末尾に足して送らなければならない
（SHALL。IHE RAD TF-2 4.13）。状態の変更と通の追加は 1 つのトランザクションで行い、
送る順・記録・再送信は照合の送信と同じにする（SHALL）。照合で作っていない予約と、
MPPS の N-SET による中止では送ってはならない（SHALL NOT）。

#### Scenario: 照合で作った予約を取消にする

- **WHEN** 照合で作った予約を画面で取消にする
- **THEN** ORC-1 が `CA` の ORM が送られ、予約の詳細の「HL7 送信」に「ORM^O01（CA）」の行が出る

#### Scenario: 予約の知らせが受理されていない

- **WHEN** NW の ORM が拒否されたままの予約を取消にする
- **THEN** CA の通は送信待ちで残り、再送信で NW、CA の順に送られる

#### Scenario: ふつうの予約を取消にする

- **WHEN** 照合で作っていない予約を取消にする
- **THEN** HL7 は送られない

#### Scenario: 組み立てに失敗する

- **WHEN** 取消の通の組み立てで誤りが起きる
- **THEN** 予約の状態も照合の記録も変わらない
