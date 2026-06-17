
1. 生成AI＋製造業向けのAIエージェントシステムを使って、製造業向けのワークフローシステムを簡単に作れるAIエージェント実行基盤を作る

2. AIエージェント基盤を使うと、今まで一品物の生成AIシステムを作らないとできなかったものが、
   設定ファイルれbルの作りこみで製造業のワークフローシステムが作れるようになる。
   AI開発者がシステムを作らなくても、営業技術ぐらいの人がシステムを構築できる

3. 製造業向けに特化しているので、Copilotなどの汎用的なものとは違う
   安全や商人、監査などが残る仕組みにする

4. Agent Coreは汎用エンジン、業務プロセスはYAML(設定ファイル)にすることでこれらのことが可能になる
   製造業務を安全に進めるためのAgent Workflow Engineをベースにした
   製造業向けのシステムコンサルティング事業

--------------------------------------

結論として、**tool callループを自作できるだけでは差別化になりません**。Copilot、Claude Code、ChatGPT系のAgentもすでに「ツールを呼ぶ・コードを読む・外部システムにつなぐ・ワークフロー化する」方向に進んでいるためです。差別化するなら、**製造業の業務判断・制約・承認・証跡・既存システム連携まで含めた“業務実行ランタイム”に寄せるべき**です。

Copilotとの差は、雑に言うとこうです。

| 観点    | Copilot / Claude Code系   | 製造業向け自前Agentで狙うべき領域    |
| ----- | ------------------------ | ---------------------- |
| 主戦場   | 汎用生産性、コーディング、Office、業務補助 | 製造現場・品質・保全・生産管理の実務完了   |
| 強み    | 汎用性、UI、モデル性能、既存エコシステム    | 業務ルール、現場データ、承認、証跡、制約条件 |
| 弱み    | 個社業務の深い判断・責任境界に入りにくい     | 汎用チャット性能やブランドでは勝ちにくい   |
| 差別化の核 | しにくい                     | 「その会社の製造業務を安全に進める」こと   |

GitHub Copilotはすでに、リポジトリを調査し、実装計画を作り、ブランチ上でコード変更し、PR作成まで進められるCloud agentを持っています。さらにcustom agentsでは、エージェントの名前・説明・利用可能ツール・MCPサーバ設定などをYAML frontmatterで定義できます。つまり「コードを読んで修正するAgent」や「ツール連携できるAgent」というだけでは、差別化しにくいです。([GitHub Docs][1])

Claude Codeも、コードベースを理解し、ファイル編集やコマンド実行を行うagentic coding toolとして提供されています。Claude Codeにはセッション中のコマンド、権限管理、コンテキスト操作、ワークフロー実行などの仕組みもあります。したがって、自作Agentが単に「ファイルを読める」「コマンドを実行できる」「修正できる」だけだと、Claude Codeにかなり近いものになります。([Anthropic][2])

Microsoft側も、Copilot Studioでエージェントを作り、Power Platform connectorsをツールとして使い、外部アプリやAPIと接続できる形を整えています。さらにCopilot Studioでは、AI agentsとworkflowsを組み合わせて業務プロセスを自動化する方向も示されています。つまり「業務システムに接続できるAI」も、すでに大手の標準機能側に寄ってきています。([Microsoft Learn][3])

なので、製造業向けで自前Agentを作る価値は、**Copilotと同じことをすることではなく、Copilotが汎用製品であるがゆえに深く入りにくい部分を取ること**です。

## 1. 差別化すべきは「チャット」ではなく「業務完了」

製造業向けAgentで一番重要なのは、ユーザーが「聞いたら答える」ではなく、**現場業務を最後まで進められること**です。

たとえば、弱い差別化はこうです。

```text
設備トラブルについて質問できる
作業手順書を検索できる
品質不良の原因候補を出せる
日報を要約できる
```

これはCopilotやChatGPTでも、データ連携すればかなりできます。

強い差別化はこうです。

```text
設備異常を検知
  ↓
該当設備・品番・ロット・過去不具合を照合
  ↓
暫定処置案を提示
  ↓
必要なら保全チケットを起票
  ↓
品質影響範囲を推定
  ↓
出荷保留が必要か判定補助
  ↓
承認者に回す
  ↓
すべて証跡として残す
```

ここまで来ると、単なるCopilotではなく、**製造業務の実行基盤**になります。

製造業では、答えが正しそうに見えるだけでは不十分です。誰が、どのデータを見て、どの判断をし、どの承認を経て、どのロットに影響したかが残らないと実務に使いにくい。ここが自前Agentの価値になります。

## 2. 製造業向けなら「業務制約」をAgentの中核にする

Copilotとの差別化で一番大きいのは、**製造業特有の制約をAgent runtimeに組み込むこと**です。

たとえば、製造業では次のような制約があります。

```text
・勝手に設備条件を変更してはいけない
・品質判定は根拠データと承認が必要
・ロット・シリアル・工程・設備の追跡が必要
・不良品処置には権限と記録が必要
・標準作業書と異なる作業は逸脱扱いになる
・現場判断と品質保証判断を分ける必要がある
・改善提案と正式変更を分ける必要がある
```

これを単なるプロンプトで守らせるのではなく、Agent側の状態遷移・権限・tool制限として実装します。

たとえば、こういう設計です。

```text
品質影響あり
  → final_answer禁止
  → 必ず evidence_collect tool
  → 必ず approval_request tool
  → 承認がなければ execute_change tool 禁止
```

つまり、LLMに「気を付けて」と言うのではなく、**危険な状態ではそもそも危険なtoolを渡さない**。これは製造業向けではかなり重要です。

## 3. 自前Agentの本当の価値は「現場システムとの深い結合」

Copilot Studioでもコネクタ連携はできますが、製造業の現場では、きれいなSaaS APIだけでは終わらないことが多いです。MES、ERP、PLM、QMS、保全管理、設備ログ、Excel、CSV、古いDB、ファイルサーバ、紙由来PDF、現場独自ツールが混在します。

自前Agentで差別化できるのは、こういう泥臭い結合です。

```text
MES:
  製造実績、工程進捗、ロット情報

ERP:
  品目、在庫、受注、購買、原価

PLM:
  図面、BOM、設計変更、部品表

QMS:
  不適合、是正処置、監査、標準書

保全:
  設備履歴、点検、故障、部品交換

現場データ:
  センサー、PLCログ、CSV、日報、Excel、画像
```

ここに対して、単に検索するだけでなく、**業務文脈に沿って読み替える**ことが差別化になります。

たとえば、ユーザーがこう聞いたとします。

```text
この不良、過去にも出ていない？
```

汎用Agentなら、文書検索して似た記録を返すだけになりがちです。

製造業向けAgentなら、理想はこうです。

```text
品番
工程
設備
金型
材料ロット
発生日
現象分類
検査項目
過去の是正処置
再発有無
横展開対象
```

こういう軸で自動的に検索・照合する。ここは製造業ドメインに寄せたAgentでないと作り込みにくいです。

## 4. 「Copilotでできること」と「自前でやる意味」を分ける

製造業向けAgentを考えるなら、まずCopilotに任せてよい領域と、自前で持つべき領域を分けるのがよいです。

Copilotに寄せてよいのは、汎用的な知的作業です。

```text
議事録要約
メール文案
Office文書作成
一般的な調査
コード補完
簡単なデータ整理
社内文書の自然言語検索
```

自前Agentが持つべきなのは、業務責任が発生する領域です。

```text
不具合調査の初動
保全対応の切り分け
生産計画変更の影響確認
出荷可否の判断補助
設計変更の影響範囲確認
標準作業書との逸脱検出
監査向け証跡生成
ロットトレース
CAPA / 是正処置支援
```

要するに、**Copilotは“人の作業を広く助けるもの”、自前Agentは“特定業務を安全に進めるもの”**として位置づけると整理しやすいです。

## 5. 差別化の軸は7つある

製造業向けで考えるなら、差別化はだいたいこの7つです。

### 1. 業務プロセスを内蔵している

単に回答するのではなく、業務フローを知っていることです。

```text
不良発生
  → 暫定処置
  → 影響範囲確認
  → 原因分析
  → 是正処置
  → 再発防止
  → 効果確認
```

この流れをAgentの状態遷移として持つと、チャットAIではなく業務Agentになります。

### 2. 証跡を残せる

製造業では、回答そのものよりも、後から説明できることが重要です。

```text
参照したデータ
使ったツール
検索条件
判断理由
承認者
実行日時
変更前後
関連ロット
```

これを自動でrun logとして残せるなら、Copilotとの差別化になります。

### 3. 権限と承認を扱える

現場では「提案」と「実行」は違います。

```text
提案:
  設備点検したほうがよい

実行:
  保全チケットを起票する

高リスク実行:
  生産停止を提案する
  出荷保留を申請する
  工程条件変更を依頼する
```

自前Agentでは、toolごとに権限、承認、dry-run、本実行を分けられます。これはプロダクション向けAgentではかなり強いです。

### 4. 現場言語に合わせられる

製造業では、同じ現象でも会社・工場・ラインごとに言葉が違います。

```text
ビビリ
カジリ
打痕
バリ
寸法飛び
チョコ停
段取り替え
手直し
流動停止
```

こういう現場語彙、略称、品番体系、工程名、設備名に合わせられるAgentは、汎用Copilotより現場に刺さります。

### 5. レガシー環境に合わせられる

製造業では、クラウド前提で動けないケースもあります。

```text
オンプレDB
閉域網
ファイルサーバ
古いWindows端末
Excel台帳
Access
CSV連携
夜間バッチ
社外持ち出し禁止
```

この環境に合わせて、ローカル実行、オンプレ配置、ネットワーク制限、ログ管理を作れるなら、自前Agentの価値が出ます。

### 6. 業務別にツール粒度を設計できる

汎用Agentでは `query_database` や `search_docs` のような粗いツールになりがちです。製造業向けでは、もっと業務語彙に寄せたツールにできます。

```text
get_lot_genealogy
find_similar_defects
check_current_work_instruction
compare_bom_revision
estimate_quality_impact
create_maintenance_ticket
request_quality_approval
generate_8d_report_draft
```

ツール名そのものが業務概念になっていると、LLMの判断も安定しやすいです。

### 7. 評価指標を業務成果に置ける

一般的なAI製品は「回答品質」や「作業時間短縮」を見がちです。製造業Agentでは、もっと実務に近い指標を置けます。

```text
不具合調査時間の短縮
過去トラ検索漏れの削減
保全一次切り分け時間の短縮
標準書逸脱の検出率
報告書作成時間の削減
承認待ち滞留の削減
横展開漏れの削減
```

これができると、「Copilotより賢い」ではなく「この業務KPIを改善する」と言えます。

## 6. 逆に、差別化になりにくいもの

ここは注意したほうがよいです。

```text
チャットUIがある
RAGで社内文書検索できる
ファイルを読める
Pythonを実行できる
コードを書ける
MCPに対応している
複数ツールを呼べる
```

これらは必要ですが、長期的な差別化にはなりにくいです。GitHub CopilotもMCPで外部システム連携を拡張でき、Copilot Studioもコネクタで外部アプリやAPIに接続できます。したがって、「ツール連携できます」はすでに一般機能になりつつあります。([GitHub Docs][4])

差別化にするなら、ツール連携ではなく、**そのツールをどの順番で、どの権限で、どの業務判断に使うか**です。

## 7. 製造業向けAgentの具体的な強いユースケース

最初に狙うなら、次のような領域がよいです。

### 不具合調査Agent

これはかなり相性がよいです。

```text
入力:
  品番、ロット、不良内容、工程、設備、画像、検査値

Agentがやること:
  過去不具合検索
  類似事例抽出
  ロット影響範囲確認
  標準書・検査基準確認
  原因候補整理
  暫定処置案
  是正処置案
  報告書ドラフト生成
```

価値は、**ベテランが頭の中でやっている横断検索を形式知化できること**です。

### 保全一次切り分けAgent

設備トラブル対応も向いています。

```text
入力:
  アラームコード、設備名、発生タイミング、直前作業、センサーログ

Agentがやること:
  過去故障履歴確認
  点検手順提示
  交換部品候補
  類似停止事例
  保全チケット起票
  生産影響見積もり
```

価値は、**保全担当に届く前の一次切り分けを標準化できること**です。

### 標準作業・手順逸脱チェックAgent

作業記録や日報、検査記録と標準書を照合する用途です。

```text
入力:
  作業日報、チェックシート、標準作業書、検査結果

Agentがやること:
  未記入確認
  手順逸脱検出
  異常値確認
  承認漏れ確認
  監査向けコメント生成
```

価値は、**監査・品質保証・現場管理に直結すること**です。

### 設計変更・BOM影響確認Agent

PLMやBOMが絡む領域です。

```text
入力:
  設計変更内容、対象部品、図面、BOM、使用製品

Agentがやること:
  影響品番確認
  使用中ロット確認
  在庫影響確認
  代替部品影響
  作業標準書の改訂対象抽出
```

価値は、**設計・生産・品質・購買のまたぎ業務を支援できること**です。

## 8. 自前で作る最大メリットは「責任境界を設計できること」

CopilotやChatGPTを使う場合、ユーザーは便利に使えますが、業務上の責任境界は曖昧になりがちです。

```text
この回答はどのデータに基づくのか
この操作は誰の承認で実行されたのか
この判断はAI提案か、人間承認済みか
この結果を監査で説明できるか
誤操作時にどこで止められるか
```

自前Agentなら、ここを設計できます。

```text
AIは提案まで
実行は人間承認後
高リスク操作は二重承認
出荷・品質・設備条件変更は直接実行禁止
全tool callを監査ログ化
根拠データを保存
回答には参照元を必ず含める
```

これは、製造業の業務システムとしてはかなり大きいです。

## 9. 製品コンセプトとしてはこう置くとよい

「製造業向けAIエージェント」をそのまま名乗ると、Copilotとの差がぼやけます。むしろ、次のように置いたほうが強いです。

```text
製造業向けCopilot
  → 弱い。汎用Copilotと比較される。

製造現場の不具合調査Agent
  → 強い。業務課題が明確。

保全一次切り分けAgent
  → 強い。対象ユーザーと成果が明確。

品質保証向け監査証跡Agent
  → 強い。Copilotでは踏み込みにくい。

MES / QMS / PLM横断の業務実行Agent
  → 強い。ただし初期実装は重い。
```

最初から「何でもできる製造業Agent」にしないほうがよいです。Copilotと正面衝突します。最初は、**1つの高頻度・高負荷・高リスク業務に絞る**ほうが差別化になります。

## 10. 技術設計として気を付けるところ

あなたが今考えているtool call中心設計を前提にすると、製造業向けではこういう設計にすると差別化しやすいです。

```text
Agent Core:
  汎用tool call loop
  final_answer / ask_user / request_approval
  max_steps
  audit log
  permission policy

Manufacturing Domain Layer:
  不良調査フロー
  保全切り分けフロー
  ロットトレース
  BOM影響確認
  標準書照合
  承認ルール

Connectors:
  MES
  ERP
  PLM
  QMS
  ファイルサーバ
  Excel / CSV
  設備ログ

UI:
  チャットだけでなく、案件単位の進捗
  根拠データ表示
  承認ボタン
  実行ログ
  差し戻し
```

この中で一番大事なのは、**Manufacturing Domain Layer**です。Agent CoreだけだとCopilotやClaude Codeに近づきます。差別化は、業務フロー、権限、証跡、システム連携、現場語彙にあります。

## 11. 最終的な判断

自前Agentを作る意味は、**ChatGPTやCopilotの代替を作ることではない**です。そこを狙うと、UI、モデル、エコシステム、ブランド、配布力で大手に負けやすいです。

自前で作る意味は、次の領域にあります。

```text
個社業務に深く入り込む
現場データを安全に扱う
承認と証跡を設計する
レガシーシステムに接続する
製造業の判断フローを状態機械として持つ
高頻度・高負荷業務を最後まで完了させる
```

したがって、製造業向けAgentの差別化は、**「AIが賢い」ではなく、「製造業務の中で安全に使える」こと**です。

一言でまとめると、狙うべき方向はこれです。

```text
Copilot:
  汎用AIアシスタント

自前の製造業Agent:
  製造業務の制約・承認・証跡・現場データを内蔵した業務実行エンジン
```

この方向なら、Copilotと競合するというより、Copilotでは踏み込みにくい現場業務の深い部分を取れます。

[1]: https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-cloud-agent?utm_source=chatgpt.com "About GitHub Copilot cloud agent"
[2]: https://www.anthropic.com/claude-code?utm_source=chatgpt.com "Claude Code by Anthropic | AI Coding Agent, Terminal, IDE"
[3]: https://learn.microsoft.com/en-us/microsoft-copilot-studio/advanced-connectors?utm_source=chatgpt.com "Use connectors in Copilot Studio agents"
[4]: https://docs.github.com/en/copilot/concepts/context/mcp?utm_source=chatgpt.com "About Model Context Protocol (MCP) - GitHub Copilot"


------


イメージとしては、**「業務プロセスをLLMのプロンプトに書くだけ」ではなく、Agent runtime側に `状態`・`許可ツール`・`次に進む条件` を持たせる**ということです。

つまり、LLMにこう言うだけでは弱いです。

```text
不良調査の流れに沿って対応してください
```

実装としては、Agent側にこういう制御を持たせます。

```text
現在の状態: 過去不具合調査中
許可するツール: search_similar_defects, ask_user
禁止するツール: final_answer, create_report
次に進む条件: 類似不具合検索結果が1回以上あること
```

要するに、**LLMが自由に業務フローを考えるのではなく、Agent runtimeが業務フローのレールを持ち、その範囲内でLLMに次のtool_callを選ばせる**という実装です。

---

たとえば「製造不良調査Agent」なら、業務プロセスをこう定義します。

```text
受付
  ↓
対象情報の確認
  ↓
過去不具合の検索
  ↓
標準書・検査基準の確認
  ↓
品質影響範囲の確認
  ↓
暫定処置案の作成
  ↓
承認依頼
  ↓
最終回答
```

これをコードでは、まず状態として持ちます。

```python
from enum import StrEnum


class DefectInvestigationState(StrEnum):
    INTAKE = "intake"
    COLLECT_CONTEXT = "collect_context"
    SEARCH_HISTORY = "search_history"
    CHECK_STANDARD = "check_standard"
    ASSESS_IMPACT = "assess_impact"
    PROPOSE_ACTION = "propose_action"
    WAIT_APPROVAL = "wait_approval"
    FINAL = "final"
```

次に、Agentの実行コンテキストに現在状態と証跡を持たせます。

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentContext:
    state: DefectInvestigationState = DefectInvestigationState.INTAKE
    evidence: dict[str, Any] = field(default_factory=dict)
    approvals: dict[str, bool] = field(default_factory=dict)
    step: int = 0

    def has_evidence(self, key: str) -> bool:
        return key in self.evidence

    def is_approved(self, key: str) -> bool:
        return self.approvals.get(key, False)
```

ここでいう `evidence` は、Agentが業務判断に使った根拠です。

```python
ctx.evidence = {
    "lot_info": {...},
    "similar_defects": [...],
    "work_instruction": "...",
    "quality_impact": {...},
}
```

これがあると、LLMがなんとなく回答するのではなく、**必要な情報が揃っているかをAgent側で判定**できます。

---

次に、状態ごとに許可するツールを決めます。

```python
def select_tools(ctx: AgentContext) -> list[str]:
    match ctx.state:
        case DefectInvestigationState.INTAKE:
            return ["ask_user", "extract_defect_context"]

        case DefectInvestigationState.COLLECT_CONTEXT:
            return ["get_lot_info", "get_product_info", "ask_user"]

        case DefectInvestigationState.SEARCH_HISTORY:
            return ["search_similar_defects", "ask_user"]

        case DefectInvestigationState.CHECK_STANDARD:
            return ["get_work_instruction", "get_inspection_standard", "ask_user"]

        case DefectInvestigationState.ASSESS_IMPACT:
            return ["estimate_quality_impact", "ask_user"]

        case DefectInvestigationState.PROPOSE_ACTION:
            return ["create_temporary_action_plan", "ask_user"]

        case DefectInvestigationState.WAIT_APPROVAL:
            return ["request_approval", "ask_user"]

        case DefectInvestigationState.FINAL:
            return ["final_answer"]
```

これがかなり重要です。

`final_answer` を常に許可しない。
`create_temporary_action_plan` も最初から許可しない。
状態に応じて、LLMが使える道具を絞ります。

これにより、Agentはこういう挙動になります。

```text
まだ過去不具合を検索していない
  → final_answer 禁止

まだ標準書を確認していない
  → 暫定処置案 禁止

品質影響が未評価
  → 承認依頼 禁止

承認されていない
  → 完了扱い禁止
```

これはプロンプトではなく、プログラム側の制御です。

---

次に、状態遷移を定義します。

```python
def update_state(ctx: AgentContext) -> None:
    if ctx.state == DefectInvestigationState.INTAKE:
        if ctx.has_evidence("defect_context"):
            ctx.state = DefectInvestigationState.COLLECT_CONTEXT
        return

    if ctx.state == DefectInvestigationState.COLLECT_CONTEXT:
        if ctx.has_evidence("lot_info") and ctx.has_evidence("product_info"):
            ctx.state = DefectInvestigationState.SEARCH_HISTORY
        return

    if ctx.state == DefectInvestigationState.SEARCH_HISTORY:
        if ctx.has_evidence("similar_defects"):
            ctx.state = DefectInvestigationState.CHECK_STANDARD
        return

    if ctx.state == DefectInvestigationState.CHECK_STANDARD:
        if ctx.has_evidence("work_instruction") and ctx.has_evidence("inspection_standard"):
            ctx.state = DefectInvestigationState.ASSESS_IMPACT
        return

    if ctx.state == DefectInvestigationState.ASSESS_IMPACT:
        if ctx.has_evidence("quality_impact"):
            ctx.state = DefectInvestigationState.PROPOSE_ACTION
        return

    if ctx.state == DefectInvestigationState.PROPOSE_ACTION:
        if ctx.has_evidence("temporary_action_plan"):
            ctx.state = DefectInvestigationState.WAIT_APPROVAL
        return

    if ctx.state == DefectInvestigationState.WAIT_APPROVAL:
        if ctx.is_approved("temporary_action_plan"):
            ctx.state = DefectInvestigationState.FINAL
        return
```

この `update_state()` が、業務プロセスを内蔵している部分です。

LLMが「もう完了です」と言っても、Agent側が `FINAL` 状態でなければ `final_answer` を許可しません。

---

Agentループはこうなります。

```python
async def run_agent(user_input: str) -> str:
    ctx = AgentContext()

    messages = [
        {
            "role": "system",
            "content": (
                "You are a manufacturing defect investigation agent. "
                "Use only the provided tools. Do not answer directly. "
                "If information is missing, call ask_user."
            ),
        },
        {
            "role": "user",
            "content": user_input,
        },
    ]

    for _ in range(20):
        allowed_tool_names = select_tools(ctx)
        tools = build_tool_defs(allowed_tool_names)

        response = await call_llm(
            messages=messages,
            tools=tools,
            tool_choice="required",
        )

        assistant_message = response.choices[0].message
        messages.append(assistant_message)

        for tool_call in assistant_message.tool_calls or []:
            name = tool_call.function.name
            args = parse_arguments(tool_call)

            if name == "final_answer":
                if ctx.state != DefectInvestigationState.FINAL:
                    raise RuntimeError("final_answer is not allowed yet")

                return args["answer"]

            if name == "ask_user":
                return args["question"]

            result = await execute_tool(name, args)

            save_evidence(ctx, name, result)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": to_json(result),
                }
            )

        update_state(ctx)
        ctx.step += 1

    raise RuntimeError("max steps exceeded")
```

この設計で大事なのは、LLMに全部任せていないことです。

```text
LLMの役割:
  現在状態で、どのツールをどう呼ぶか判断する

Agent runtimeの役割:
  どの状態か管理する
  どのツールを許可するか決める
  必要な証跡が揃ったか確認する
  次の状態へ進める
  危険操作を止める
```

この分担にすると、業務プロセスが実装になります。

---

具体的に「過去不具合検索」が終わったら、こういう結果を保存します。

```python
def save_evidence(ctx: AgentContext, tool_name: str, result: dict) -> None:
    if tool_name == "extract_defect_context":
        ctx.evidence["defect_context"] = result

    elif tool_name == "get_lot_info":
        ctx.evidence["lot_info"] = result

    elif tool_name == "get_product_info":
        ctx.evidence["product_info"] = result

    elif tool_name == "search_similar_defects":
        ctx.evidence["similar_defects"] = result

    elif tool_name == "get_work_instruction":
        ctx.evidence["work_instruction"] = result

    elif tool_name == "get_inspection_standard":
        ctx.evidence["inspection_standard"] = result

    elif tool_name == "estimate_quality_impact":
        ctx.evidence["quality_impact"] = result

    elif tool_name == "create_temporary_action_plan":
        ctx.evidence["temporary_action_plan"] = result

    elif tool_name == "request_approval":
        ctx.approvals["temporary_action_plan"] = result["approved"]
```

ここも汎用Agentとの差別化ポイントです。
ただツール結果をLLMに返すだけでなく、**業務上の意味を持った証跡として保存**します。

---

たとえばユーザーがこう入力したとします。

```text
品番A-100の寸法不良が出た。過去にも同じような事例があるか確認して、暫定処置案を出して。
```

このとき、Agentは内部でこう進みます。

```text
INTAKE
  extract_defect_context
  → 品番A-100、現象=寸法不良 を抽出

COLLECT_CONTEXT
  get_lot_info
  get_product_info

SEARCH_HISTORY
  search_similar_defects

CHECK_STANDARD
  get_work_instruction
  get_inspection_standard

ASSESS_IMPACT
  estimate_quality_impact

PROPOSE_ACTION
  create_temporary_action_plan

WAIT_APPROVAL
  request_approval

FINAL
  final_answer
```

ユーザーから見ると普通に会話しているだけですが、内部では業務プロセスに沿って進んでいます。

---

ここでCopilot的な汎用チャットと違うのは、次の点です。

```text
汎用チャット:
  LLMが「過去事例を確認しましょう」と文章で言う

業務Agent:
  search_similar_defects tool を実際に呼ぶ
  結果を evidence["similar_defects"] に保存する
  その結果がない限り次工程に進めない
```

つまり、**業務プロセスを“説明できる”のではなく、“実行制御として持っている”**という違いです。

---

最初から大きく作る必要はありません。最小実装なら、この4つだけでよいです。

```text
1. State
   今どの業務段階か

2. Allowed tools
   その状態で使ってよいツール

3. Evidence
   次に進むために必要な根拠データ

4. Transition
   根拠が揃ったら次状態へ進む
```

コード上の最小構成はこうです。

```python
@dataclass
class WorkflowPolicy:
    state: DefectInvestigationState

    def allowed_tools(self) -> list[str]:
        ...

    def can_transition(self, ctx: AgentContext) -> bool:
        ...

    def next_state(self) -> DefectInvestigationState:
        ...
```

さらに整理するなら、状態定義をデータとして持つこともできます。

```python
WORKFLOW = {
    DefectInvestigationState.COLLECT_CONTEXT: {
        "allowed_tools": ["get_lot_info", "get_product_info", "ask_user"],
        "required_evidence": ["lot_info", "product_info"],
        "next": DefectInvestigationState.SEARCH_HISTORY,
    },
    DefectInvestigationState.SEARCH_HISTORY: {
        "allowed_tools": ["search_similar_defects", "ask_user"],
        "required_evidence": ["similar_defects"],
        "next": DefectInvestigationState.CHECK_STANDARD,
    },
    DefectInvestigationState.CHECK_STANDARD: {
        "allowed_tools": ["get_work_instruction", "get_inspection_standard", "ask_user"],
        "required_evidence": ["work_instruction", "inspection_standard"],
        "next": DefectInvestigationState.ASSESS_IMPACT,
    },
}
```

この場合、状態遷移は汎用化できます。

```python
def update_state(ctx: AgentContext) -> None:
    rule = WORKFLOW.get(ctx.state)
    if rule is None:
        return

    required = rule["required_evidence"]

    if all(key in ctx.evidence for key in required):
        ctx.state = rule["next"]
```

最初はこのくらいで十分です。

---

実装の本質は、**LLMに業務プロセスを覚えさせるのではなく、Agent側が業務プロセスを状態機械として持つこと**です。

```text
プロンプトだけ:
  「不良調査の流れで回答して」
  → たまに飛ばす
  → 根拠不足でも答える
  → 承認前に完了扱いする

状態機械あり:
  state = SEARCH_HISTORY
  → search_similar_defects しか許可しない
  → 結果がないと次に進まない
  → final_answer は最後まで許可しない
```

製造業向けAgentで差別化になるのは、この後者です。
**LLMの賢さではなく、業務上やってはいけない進み方をAgent runtimeが防ぐ**。これが「業務プロセスを内蔵している」の実装イメージです。



------


かなり良い方向だと思います。むしろ製造業向けAgentで差別化するなら、**Agent Coreは汎用エンジンにして、業務プロセスはYAMLなどの宣言的設定で差し替えられる**形がかなり強いです。

ただし、全部をYAML化するのではなく、分け方が重要です。

```text
YAMLに寄せるもの:
  業務フロー
  状態
  状態ごとの許可ツール
  次状態へ進む条件
  必須証跡
  承認ルール
  final_answerを許可する条件
  プロンプト断片
  出力テンプレート

Pythonに残すもの:
  tool本体
  LLM呼び出し
  YAML検証
  状態遷移エンジン
  権限チェック
  監査ログ
  例外処理
  セキュリティ制御
```

これは方向性として既存のAgentフレームワークとも合っています。LangGraphは長時間動く状態付きworkflow / agentのための低レベル基盤として説明されており、OpenAI Agents SDKもagentをinstructions、tools、handoffs、guardrails、structured outputsなどを持つ実行単位として扱っています。CrewAIもagentsやcrewsの定義にYAML設定を推奨しています。つまり「Agentをコードだけで組むのではなく、設定・状態・ワークフローとして定義したい」という方向はすでに自然な流れです。([LangChain Docs][1])

特に興味深いのは、2026年のAgentSPEXという研究では、従来のAgentがreactive promptingに依存して制御フローや中間状態が暗黙になりがちで、LangGraphやCrewAIのようなフレームワークは構造化を進める一方でPythonロジックと結びつきやすい、という問題意識から、明示的な制御フロー・状態管理・分岐・ループ・サブモジュールを持つAgent仕様言語を提案しています。これは、あなたが言っている「YAML設定で業務Agentを動かす」にかなり近い発想です。([arXiv][2])

## 目指す形は「YAML駆動の業務Agentランタイム」

実装イメージはこうです。

```text
agent-core
  ├─ LLM Client
  ├─ Tool Registry
  ├─ Workflow Engine
  ├─ Policy Engine
  ├─ Evidence Store
  ├─ Audit Logger
  └─ YAML Loader

workflow yaml
  ├─ 状態定義
  ├─ 許可ツール
  ├─ 必須証跡
  ├─ 遷移条件
  ├─ 承認条件
  └─ final_answer条件
```

つまり、Python側は「実行エンジン」で、YAML側は「業務定義」です。

製造業向けなら、たとえば以下をYAMLで定義できると強いです。

```text
不良調査Agent
保全一次切り分けAgent
標準作業逸脱チェックAgent
BOM影響確認Agent
監査証跡作成Agent
```

同じAgent Coreのまま、YAMLを差し替えるだけで業務Agentを増やせます。

## YAML例

たとえば、不良調査Agentならこういう定義になります。

```yaml
id: defect_investigation
name: 不良調査Agent
version: 1.0.0

initial_state: intake
max_steps: 20

control_tools:
  - ask_user
  - final_answer
  - request_approval

states:
  intake:
    description: ユーザー入力から不良内容を抽出する
    allowed_tools:
      - extract_defect_context
      - ask_user
    required_evidence:
      - defect_context
    transitions:
      - to: collect_context
        when: has_evidence("defect_context")

  collect_context:
    description: 品番、ロット、工程、設備などの基本情報を集める
    allowed_tools:
      - get_lot_info
      - get_product_info
      - get_process_info
      - ask_user
    required_evidence:
      - lot_info
      - product_info
    transitions:
      - to: search_history
        when: has_all_evidence(["lot_info", "product_info"])

  search_history:
    description: 過去の類似不良を検索する
    allowed_tools:
      - search_similar_defects
      - ask_user
    required_evidence:
      - similar_defects
    transitions:
      - to: check_standard
        when: has_evidence("similar_defects")

  check_standard:
    description: 標準作業書と検査基準を確認する
    allowed_tools:
      - get_work_instruction
      - get_inspection_standard
      - ask_user
    required_evidence:
      - work_instruction
      - inspection_standard
    transitions:
      - to: assess_impact
        when: has_all_evidence(["work_instruction", "inspection_standard"])

  assess_impact:
    description: 品質影響範囲を評価する
    allowed_tools:
      - estimate_quality_impact
      - ask_user
    required_evidence:
      - quality_impact
    transitions:
      - to: propose_action
        when: has_evidence("quality_impact")

  propose_action:
    description: 暫定処置案を作成する
    allowed_tools:
      - create_temporary_action_plan
      - ask_user
    required_evidence:
      - temporary_action_plan
    transitions:
      - to: wait_approval
        when: has_evidence("temporary_action_plan")

  wait_approval:
    description: 暫定処置案の承認を取得する
    allowed_tools:
      - request_approval
      - ask_user
    required_approvals:
      - temporary_action_plan
    transitions:
      - to: final
        when: is_approved("temporary_action_plan")

  final:
    description: ユーザーへ最終回答する
    allowed_tools:
      - final_answer
    final: true

final_answer:
  allowed_states:
    - final
  require_evidence:
    - defect_context
    - lot_info
    - product_info
    - similar_defects
    - work_instruction
    - inspection_standard
    - quality_impact
    - temporary_action_plan
```

これができると、コードに不良調査専用のif文を書かなくても、状態遷移をYAMLで管理できます。

## Python側の実装はどうなるか

Python側は、YAMLを読んでこう動くだけです。

```python
@dataclass
class WorkflowContext:
    workflow_id: str
    state: str
    evidence: dict[str, Any] = field(default_factory=dict)
    approvals: dict[str, bool] = field(default_factory=dict)
    step: int = 0
```

メインループはかなり汎用になります。

```python
async def run_workflow(user_input: str, workflow: WorkflowDefinition) -> str:
    ctx = WorkflowContext(
        workflow_id=workflow.id,
        state=workflow.initial_state,
    )

    messages = [
        {"role": "system", "content": workflow.system_prompt()},
        {"role": "user", "content": user_input},
    ]

    for _ in range(workflow.max_steps):
        state_def = workflow.states[ctx.state]

        allowed_tools = tool_registry.resolve(state_def.allowed_tools)

        response = await llm.call(
            messages=messages,
            tools=allowed_tools,
            tool_choice="required",
        )

        assistant_message = response.choices[0].message
        messages.append(assistant_message)

        for tool_call in assistant_message.tool_calls or []:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)

            if name == "final_answer":
                workflow.assert_final_allowed(ctx)
                return args["answer"]

            if name == "ask_user":
                return args["question"]

            result = await tool_registry.execute(name, args)

            evidence_key = workflow.map_tool_to_evidence(name)
            if evidence_key:
                ctx.evidence[evidence_key] = result

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

            audit_log.record(
                workflow_id=workflow.id,
                state=ctx.state,
                tool=name,
                args=args,
                result=result,
            )

        ctx.state = workflow.next_state(ctx)
        ctx.step += 1

    raise RuntimeError("max steps exceeded")
```

この形にすると、不良調査Agentも保全AgentもBOM影響確認Agentも、同じランタイムで動かせます。違うのはYAMLだけです。

## YAML化の一番大きいメリット

最大のメリットは、**業務知識をコードから分離できること**です。

製造業では、業務フローは現場・工場・顧客ごとに違います。コードに埋め込むと、顧客A向け、顧客B向け、部署C向けで分岐だらけになります。

YAML化すると、こうできます。

```text
agent-core:
  共通

workflows/customer_a/defect_investigation.yaml:
  A社の不良調査フロー

workflows/customer_b/defect_investigation.yaml:
  B社の不良調査フロー

workflows/customer_a/maintenance_triage.yaml:
  A社の保全一次切り分けフロー
```

これは製品化を考えるとかなり大きいです。

```text
コード変更なしで業務フローを調整できる
顧客別・工場別・ライン別に設定を分けられる
YAMLをGit管理できる
レビュー・承認できる
変更履歴を追える
監査しやすい
```

製造業向けでは、これは強いです。単なるAIチャットではなく、**業務ルールを設定として持つAgent基盤**になります。

## ただし、YAMLに入れすぎると壊れる

注意点もあります。YAML化は強力ですが、やりすぎると自作の低品質プログラミング言語になります。

避けたほうがよいのはこういう設計です。

```yaml
when: "ctx.evidence['lot_info']['status'] == 'NG' and len(ctx.evidence['similar_defects']) > 0"
```

これを許すと、YAML内に疑似Pythonが増えます。危険ですし、テストも難しくなります。

おすすめは、条件式を限定されたDSLにすることです。

```yaml
when:
  all:
    - has_evidence: lot_info
    - has_evidence: product_info
```

またはこうです。

```yaml
transitions:
  - to: search_history
    conditions:
      - type: has_evidence
        key: lot_info
      - type: has_evidence
        key: product_info
```

Python側で許可された条件だけ評価します。

```python
def evaluate_condition(ctx: WorkflowContext, condition: dict) -> bool:
    match condition["type"]:
        case "has_evidence":
            return condition["key"] in ctx.evidence

        case "has_all_evidence":
            return all(key in ctx.evidence for key in condition["keys"])

        case "is_approved":
            return ctx.approvals.get(condition["key"], False)

        case _:
            raise ValueError(f"unknown condition: {condition['type']}")
```

これなら安全で、検証しやすいです。

## 実用設計ではYAMLを3層に分けるとよい

全部を1つのYAMLに詰めるより、3つに分けると扱いやすいです。

```text
1. workflow.yaml
   業務フロー、状態、遷移、承認条件

2. tools.yaml
   ツール名、説明、引数スキーマ、リスクレベル

3. prompts.yaml
   状態ごとの指示、回答方針、禁止事項
```

たとえば。

```text
workflows/
  defect_investigation/
    workflow.yaml
    prompts.yaml
    tools.yaml
```

`workflow.yaml` はこう。

```yaml
id: defect_investigation
initial_state: intake
states:
  intake:
    allowed_tools:
      - extract_defect_context
      - ask_user
    transitions:
      - to: collect_context
        conditions:
          - type: has_evidence
            key: defect_context
```

`tools.yaml` はこう。

```yaml
tools:
  search_similar_defects:
    implementation: manufacturing.defects.search_similar_defects
    risk: read_only
    evidence_key: similar_defects

  request_approval:
    implementation: manufacturing.approval.request_approval
    risk: approval_required

  update_quality_status:
    implementation: manufacturing.quality.update_quality_status
    risk: high
    requires_approval: true
```

`prompts.yaml` はこう。

```yaml
system: |
  You are a manufacturing workflow agent.
  Use only the provided tools.
  Do not answer directly unless final_answer is available.

states:
  assess_impact: |
    Evaluate quality impact using only collected evidence.
    Do not guess missing lot or process information.
    If information is missing, call ask_user.

  final: |
    Produce a concise final answer.
    Include referenced evidence keys and unresolved risks.
```

この分割にすると、業務担当者、開発者、運用者の責任範囲を分けやすいです。

## 差別化としてかなり強い

これはCopilotとの差別化にもなります。

Copilot的なものは、基本的には「強い汎用AI + 接続先 + UI」です。一方、YAML駆動の製造業Agentは、**業務ルールをプロダクトの中心に置く**ことができます。

```text
Copilot:
  ユーザーの依頼に柔軟に答える

YAML駆動の製造業Agent:
  定義された業務フローに沿って進める
  必須証跡がないと次へ進めない
  承認がないと実行できない
  顧客別フローを設定で切り替えられる
  監査ログを残せる
```

この違いは大きいです。

OpenAI Agents SDKにもtracingがあり、LLM生成、tool call、handoff、guardrails、custom eventsなどを記録できると説明されています。製造業向けで自前化するなら、これに近い考え方を業務証跡として持つとよいです。([OpenAI GitHub Pages][3])

## 最小実装の現実的な範囲

最初から完全なYAML Agent Frameworkにする必要はありません。まずはこのくらいで十分です。

```text
Phase 1:
  workflow.yamlで状態・許可ツール・必須証跡を定義

Phase 2:
  承認ルール、risk level、final_answer条件を追加

Phase 3:
  顧客別・工場別workflowを読み替え

Phase 4:
  UIからworkflowを編集・検証

Phase 5:
  ワークフロー実行ログ、再実行、差分比較、監査対応
```

最初のMVPでは、YAMLの表現力は絞ったほうがよいです。

```yaml
states
allowed_tools
required_evidence
transitions
final
```

この5つだけでかなり作れます。

## 私ならこう設計します

最初のコアはこの構成にします。

```text
agent-core/
  runtime.py          # 汎用Agentループ
  workflow.py         # YAMLをPydanticで読み込む
  conditions.py       # 遷移条件評価
  tool_registry.py    # ツール名と実装の対応
  policy.py           # 権限・承認・risk制御
  audit.py            # tool call / evidence / state遷移ログ
  llm.py              # LiteLLM / OpenAI互換API呼び出し

workflows/
  defect_investigation/
    workflow.yaml
    prompts.yaml
    tools.yaml
```

YAMLは必ずPydanticで型検証します。

```python
class Transition(BaseModel):
    to: str
    conditions: list[Condition]


class StateDef(BaseModel):
    description: str | None = None
    allowed_tools: list[str]
    required_evidence: list[str] = []
    transitions: list[Transition] = []
    final: bool = False


class WorkflowDef(BaseModel):
    id: str
    name: str
    version: str
    initial_state: str
    max_steps: int = 20
    states: dict[str, StateDef]
```

ここまで作ると、Agent Coreはかなり汎用になります。

## 重要な注意点

YAML駆動にするときに気を付けるべき点は明確です。

```text
1. YAMLから任意コード実行させない
2. 条件式は限定DSLにする
3. tool実装はPython側でregistry登録する
4. YAMLはPydanticで厳格に検証する
5. workflow versionを持つ
6. 実行時に使用したYAML versionをログに残す
7. 承認が必要なtoolはYAMLだけで解除できないようにする
8. final_answerを許可する状態を制限する
```

特に7が重要です。

YAMLだけでこう書けば危険操作できる、という状態は避けるべきです。

```yaml
allowed_tools:
  - update_quality_status
  - stop_production_line
```

高リスクtoolは、YAMLに書いてあってもPython側のpolicyで止めるべきです。

```python
if tool.risk == "high" and not ctx.has_approval(tool.name):
    raise PermissionError("approval required")
```

つまり、YAMLは業務定義であって、最終的な安全装置ではありません。安全装置はコード側に置きます。

## まとめ

この発想はかなり有望です。製造業向けAgentとしては、単なるtool call実装よりも、**YAMLで業務フローを宣言し、Agent Coreがそれを状態機械として実行する**ほうがはるかに差別化しやすいです。

最終的にはこういう製品思想になります。

```text
Agent Core:
  汎用実行エンジン

Workflow YAML:
  業務プロセス定義

Tools:
  MES / QMS / PLM / ERP / ファイルサーバ等への接続

Policy:
  権限・承認・監査・リスク制御
```

これは「製造業向けCopilot」ではなく、**製造業務を安全に進めるためのAgent Workflow Engine**に近いです。そこまで行くと、汎用Copilotとはかなり違う立ち位置になります。

[1]: https://docs.langchain.com/oss/python/langgraph/overview?utm_source=chatgpt.com "LangGraph overview - Docs by LangChain"
[2]: https://arxiv.org/abs/2604.13346?utm_source=chatgpt.com "AgentSPEX: An Agent SPecification and EXecution Language"
[3]: https://openai.github.io/openai-agents-python/tracing/?utm_source=chatgpt.com "Tracing - OpenAI Agents SDK"
