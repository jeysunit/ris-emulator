# Spec Delta

## MODIFIED Requirements

### Requirement: MPPS と予約を結び付ける

N-CREATE の Scheduled Step Attributes Sequence (0040,0270) の項目ごとに、Accession Number
(0008,0050) と Scheduled Procedure Step ID (0040,0009) の両方が一致する予約を探し、MPPS に
結び付けなければならない（SHALL）。1つの MPPS に複数の予約が結び付いてよい。Accession
Number が空の項目は、Study Instance UID と MPPS の Patient ID で照合で作った予約を探して
結び付ける（pir-reconciliation の「照合の後に同じ Study で届く撮影」）。一致する予約が
無い項目は、予定の無い撮影として MPPS だけを記録する。

#### Scenario: 予約を撮影する

- **WHEN** 予定の予約の受付番号と Scheduled Procedure Step ID を Scheduled Step Attributes Sequence に入れた N-CREATE（IN PROGRESS）が届く
- **THEN** 応答の Status は 0000H になり、予約の状態は実施中になる

#### Scenario: 2件の予約をまとめて撮影する

- **WHEN** 2件の予約の項目を Scheduled Step Attributes Sequence に入れた N-CREATE（IN PROGRESS）が届く
- **THEN** 2件とも実施中になる

#### Scenario: 予定の無い撮影

- **WHEN** Scheduled Procedure Step ID が空で、どの予約にも一致しない N-CREATE（IN PROGRESS）が届く
- **THEN** 応答の Status は 0000H になり、MPPS は記録され、どの予約も変わらない

#### Scenario: 受付番号のある項目は Study Instance UID で探さない

- **WHEN** 受付番号が入っていてどの予約にも一致せず、Study Instance UID が照合で作った予約と同じ項目の N-CREATE が届く
- **THEN** MPPS はどの予約にも結び付かない
