# ShogiBench Long Stat Block 先後別統計表示設計

## 概要

ShogiBench のテスト詳細ページにあるコピー可能な Long Stat Block に、将棋対局の先後別勝敗、Dev/Base の先後別勝率、先後別引き分け数、入玉宣言勝ち数を追加する。

既存の Elo、SPRT、LLR、W/L/D、Pentanomial 表示は変更せず、その下に将棋固有の詳細統計を追加する。宣言勝ちは shogitest の `GameOutcome::WinInImpasse` だけを対象とし、`WinByAdjudication` は含めない。

## 目的

- 先手勝ち数・後手勝ち数と、それぞれの割合を Long Stat Block で確認できるようにする。
- Dev/Base ごとの全体勝率、先手時勝率、後手時勝率を確認できるようにする。
- Dev/Base が先手・後手だった場合の引き分け数を確認できるようにする。
- 入玉宣言勝ちを全体、先後別、Dev/Base 別に確認できるようにする。
- Copy Stat Block でコピーしたプレーンテキストだけで、分母と集計方向を誤解なく判断できるようにする。

## 対象外

- 一覧ページの Short Stat Block は変更しない。
- `WinByAdjudication`、詰み、投了、時間切れ、違法手など、入玉宣言勝ち以外の終局理由は新しい表示に追加しない。
- shogitest の標準出力形式は変更しない。
- PGN の保存形式は変更しない。
- Chess/FRC の Long Stat Block には将棋固有統計を表示しない。

## 表示設計

Long Stat Block は現在と同じ等幅プレーンテキストを維持し、既存行の後ろに次のセクションを追加する。

```text
Elo    | 12.34 +- 3.21 (95%)
SPRT   | 8.0+0.08s Threads=1 Hash=16MB
LLR    | 1.42 (-2.25, 2.89) [0.00, 4.00]
Games  | N: 1000 W: 510 L: 440 D: 50
Penta  | [100, 180, 250, 270, 200]

Side results
Sente  | W: 505/1000 (50.5%)
Gote   | W: 445/1000 (44.5%)
Draw   | D:  50/1000 ( 5.0%)

Engine results
Engine | Overall W        | Sente W         | Gote W          | Draw S/G
Dev    | 510/1000 (51.0%) | 270/500 (54.0%) | 240/500 (48.0%) | 25 / 25
Base   | 440/1000 (44.0%) | 235/500 (47.0%) | 205/500 (41.0%) | 25 / 25

Impasse declarations
Total  | 4  (Sente: 3, Gote: 1)
Dev    | 3  (Sente: 2, Gote: 1)
Base   | 1  (Sente: 1, Gote: 0)
```

`Impasse declarations` という名称を使用し、勝敗判定による `WinByAdjudication` と区別する。

### 部分データと旧データ

新しい詳細統計を送信しない旧 worker の結果が含まれる場合、詳細統計の対象局数を明示する。

```text
Side stats coverage | N: 800/1000 (partial)
```

この場合、新しいセクションの件数と割合は、詳細統計を取得できた800局だけを分母として計算する。既存の `Games` 行は従来どおり全1000局を表示する。

既存テストなど、詳細統計を1局も取得していない場合は、誤ってゼロ件として表示せず、次の1行だけを表示する。

```text
Side stats | unavailable (legacy worker data)
```

## 集計定義

### 全体の先後別結果

- `Sente W`: 詳細統計対象局における先手勝ち数 ÷ 詳細統計対象局数
- `Gote W`: 詳細統計対象局における後手勝ち数 ÷ 詳細統計対象局数
- `Draw`: 詳細統計対象局における引き分け数 ÷ 詳細統計対象局数

3つの件数の合計は詳細統計対象局数と一致しなければならない。

### エンジン別結果

- `Overall W`: 対象エンジンの勝ち数 ÷ 詳細統計対象局数
- `Sente W`: 対象エンジンが先手だった勝ち数 ÷ 対象エンジンが先手だった対局数
- `Gote W`: 対象エンジンが後手だった勝ち数 ÷ 対象エンジンが後手だった対局数
- `Draw S/G`: 対象エンジンが先手だった場合と後手だった場合の引き分け数

割合は小数第1位まで表示する。分母が0の場合は `0/0 (N/A)` と表示し、0%とは表示しない。

### 入玉宣言勝ち

- `Total`: `WinInImpasse` の総数
- `Sente` / `Gote`: 宣言した側の先後別件数
- `Dev` / `Base`: 宣言勝ちしたエンジン別件数

`WinByAdjudication` はこの集計に含めない。

## 利用可能なshogitest出力

shogitest は現在、各対局終了時に次の形式を標準出力へ出している。

```text
Finished game 1 (engine-dev vs engine-base): 1-0 {Sente wins by impasse}
```

この1行から必要な情報を取得できる。

- 括弧内の先頭エンジンは先手、後方エンジンは後手。
- `1-0`、`0-1`、`1/2-1/2` から先後別勝敗を取得できる。
- `Sente wins by impasse` または `Gote wins by impasse` から `WinInImpasse` を判別できる。
- ShogiBench worker が渡すエンジン名は `-dev` または `-base` で終わるため、Dev/Base と先後の対応を判別できる。

したがって、今回の要件のために shogitest の出力を追加・変更しない。ShogiBench 側に現在の出力形式を固定する契約テストを置き、将来shogitestの文言が変わった場合に検出する。

## データフロー

```text
shogitest Finished game行
    -> Client/worker.py が1局ごとの詳細結果を解析
    -> 対局ペア完了時に既存W/L/D・Pentanomialと一緒にキューへ格納
    -> clientSubmitResults POSTへ詳細カウンターを追加
    -> OpenBenchサーバーがTestとResultへ原子的に加算
    -> longStatBlock() が派生値・割合を計算
    -> workload.html の既存Long Stat Blockへ表示
```

## workerの解析

`MatchRunner.update_results()` に、shogitest の終了行全体を解析する正規表現を追加する。

解析対象は次の要素である。

- 1始まりのゲーム番号
- 先手エンジン名
- 後手エンジン名
- `1-0`、`0-1`、`1/2-1/2`
- 波括弧内の終局理由全文

終局理由には `Draw by adjudication: Reached move limit` のようにコロンが含まれるため、現在の単純な `split(':')` には依存せず、行末の波括弧まで一括して取得する。

各対局について次のカウンターを更新する。

- `side_stats_games`
- `dev_sente_wins`
- `dev_gote_wins`
- `base_sente_wins`
- `base_gote_wins`
- `dev_sente_draws`
- `dev_gote_draws`
- `dev_sente_impasse_wins`
- `dev_gote_impasse_wins`
- `base_sente_impasse_wins`
- `base_gote_impasse_wins`

Baseの先後別引き分け数は次のように導出できるため、重複保存しない。

- Base先手引き分け数 = Dev後手引き分け数
- Base後手引き分け数 = Dev先手引き分け数

新しいカウンターは、既存の Trinomial/Pentanomial と同じく対局ペアが完成した時点で results queue に積み、送信後にリセットする。

## workerからサーバーへの送信

`clientSubmitResults` のPOST payloadに上記11カウンターを追加する。サーバーは `request.POST.get(field, 0)` で受け取り、旧workerからフィールドが送られない場合は0として扱う。

Chess/FRC のworker実行では新フィールドを送らないか、すべて0として送る。将棋かどうかは既存の `MatchRunner.is_shogi(config)` の判定を再利用する。

## サーバーデータモデル

`Test` と `Result` の双方に、worker送信と同名の `IntegerField(default=0)` を追加する。

`Test` はLong Stat Blockの集計元として使用する。`Result`にも保存し、worker・マシン単位の結果と総計の整合を保つ。すべて既存の結果更新トランザクション内で加算する。

派生値はDBに重複保存せず、表示時に計算する。

- 先手勝ち総数 = `dev_sente_wins + base_sente_wins`
- 後手勝ち総数 = `dev_gote_wins + base_gote_wins`
- Dev勝ち総数 = `dev_sente_wins + dev_gote_wins`
- Base勝ち総数 = `base_sente_wins + base_gote_wins`
- 詳細引き分け総数 = `dev_sente_draws + dev_gote_draws`
- Dev先手局数 = `dev_sente_wins + base_gote_wins + dev_sente_draws`
- Dev後手局数 = `dev_gote_wins + base_sente_wins + dev_gote_draws`
- Base先手局数 = Dev後手局数
- Base後手局数 = Dev先手局数

## Long Stat Block生成

`OpenBench/templatetags/mytags.py` の `longStatBlock()` を拡張する。複雑な集計をテンプレートへ持ち込まず、モデルまたは専用の純粋関数で表示用統計を組み立てる。

既存のElo/SPRT/Games/Penta行は内容・順序とも変更しない。追加セクションは将棋の詳細統計が存在する場合だけ表示する。

Copy Stat Blockは既存の `long-statblock` 要素全体をコピーするため、コピー処理の変更は不要である。

## エラー処理と整合性

### 解析失敗

詳細行の解析に失敗した場合、従来のW/L/D集計を止めない。詳細カウンターだけを加算せず、該当行をworkerログへ警告として出す。これによりLong Stat Blockはcoverageをpartialとして表示できる。

### エンジン役割の判別失敗

先手・後手エンジンの一方が `-dev`、他方が `-base` と判別できない場合は詳細統計に加えない。推測でDev/Baseを割り当てない。

### サーバー検証

1回の送信について次を検証する。

- すべてのカウンターが0以上である。
- 先手勝ち、後手勝ち、引き分けの合計が `side_stats_games` と一致する。
- 入玉宣言勝ちは対応する先後・エンジン勝ち数を超えない。
- 詳細統計のゲーム数が同じpayloadのTrinomialゲーム数を超えない。

不正なpayloadは既存集計へ加算せず、エラー応答とログを残す。

## 後方互換性と展開順序

1. DB migration、任意フィールド受信、coverage表示を含むサーバー側を先に配備する。
2. 新しい詳細カウンターを送るworkerを配布する。
3. worker更新後の新規対局から詳細統計が蓄積される。
4. 旧workerと新workerが混在する期間は `Side stats coverage` を表示する。
5. 完全なcoverageを必須にする場合だけ、別途client minimum versionを更新する。

shogitestのバージョン更新は不要である。

## テスト設計

### worker単体テスト

次の終了行を入力し、詳細カウンターを確認する。

- Dev先手勝ち
- Dev後手勝ち
- Base先手勝ち
- Base後手勝ち
- Dev先手時の引き分け
- Dev後手時の引き分け
- Dev/Baseそれぞれの先手・後手 `WinInImpasse`
- `WinByAdjudication` が宣言勝ちに含まれないこと
- コロンを含む終局理由を最後まで解析できること
- 不正な終了行で従来W/L/D経路を壊さず、詳細coverageだけが増えないこと

### サーバー単体テスト

- 新フィールドを含むpayloadが `Test` と `Result` に原子的に加算されること。
- 新フィールドを含まない旧worker payloadを受理できること。
- 不正な負数・不整合payloadを拒否すること。
- 複数回・複数workerからの加算で値を失わないこと。

### 表示テスト

- 完全coverageで承認済み表示例と一致すること。
- 部分coverageで `N: 詳細局数/全局数 (partial)` を表示すること。
- 旧データで `unavailable (legacy worker data)` を表示すること。
- 分母0の割合が `N/A` になること。
- Chess/FRCのLong Stat Blockが変わらないこと。
- Short Stat Blockが変わらないこと。
- Copy Stat Blockに追加行が含まれること。

## 完了条件

- 新workerで実行した将棋テストのLong Stat Blockに、承認済みの先後別・エンジン別・入玉宣言勝ち表示が出る。
- 表示される全割合が本設計の分母定義と一致する。
- `WinInImpasse`だけが宣言勝ちとして集計される。
- 旧データ・部分データをゼロ件の完全データとして誤表示しない。
- Chess/FRC、Short Stat Block、既存W/L/D・Pentanomial集計に回帰がない。
