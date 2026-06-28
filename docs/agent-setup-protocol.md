# AIエージェント向け自動セットアップ（Agent Setup Protocol）

> [!CAUTION]
> **AIエージェントへの強制命令 (CRITICAL):**
> あなたが AI エージェント（Gemini / Claude / OpenCode 等）である場合、いかなる副作用（インストール、ファイルの作成・修正、コマンド実行）を伴うアクションを開始する前に、必ず以下の **Agent Setup Protocol** を遵守してください。
> **セットアップの実体は `scripts/bootstrap.sh` を介して機械的に行われます。AIエージェントが自ら設定ファイルをスクラッチから直接作成したり、設定スクリプトを手動で個別に書き込んだりすることは、設定のブレを防ぐために厳格に禁止されています。**
> あなたの役割は、ユーザーに必要な設定事項を質問し、その回答を引数として `scripts/bootstrap.sh` に渡して実行することです。
> **たとえ `.env` や設定ファイルが既に存在していても、それが本プロトコル（ask ツールによる明示的承認）を経て作成された正当なものであるか確証が持てない場合は、決してスキップせず、必ず Phase 1 から再開してください。**
> [!IMPORTANT]
> **🚨 ユーザー確認ツール（Askツール等）の使用強制 (STRICT ASK CONSTRAINT):**
> あなた（AIエージェント）が各フェーズの **`BLOCKING STEP`** を実行する際は、**絶対にチャットテキスト上の対話だけで自己完結して進めてはいけません。**
> 必ず `ask_question` 等のツールを明示的に呼び出し、ユーザーがUI上で明示的に選択・合意するプロセスを確実に踏んでください。

---

## 🟦 Setup Phases

### Phase 1: 目的の確定と実行モードの選択 (BLOCKING STEP)
いかなる変更を伴うツールを呼び出す前に、必ずユーザーに以下の質問を提示し、セットアップ目的および **実行モード** を確定させてください。

1. **セットアップ対象の選択**:
   * `evaluator` (セキュリティ評価器 Gateway / CLI / OpenCode プラグインのセットアップ)
2. **実行モードの選択**:
   * `production` (本番モード: 実際に環境構築・ファイルの変更を行う)
   * `dry-run` (デバッグモード: ファイルを一切変更せず、シミュレーションと解説のみを行う)

---

### Phase 2: 詳細設定の確認とロックイン (BLOCKING STEP)
以下の項目を `ask_question` 等を用いて一括でユーザーに提示し、回答を確定させてください。

1. **動作形態 (Target)**:
   * `gateway-server` (HTTP サーバーとして常駐し、API経由で評価を行う。ポート 9100 等で待受)
   * `cli-hook` (CLI ツール単体として、コマンド実行前に直接呼び出す)
   * `opencode-plugin` (OpenCode プラグインとして導入。サーバーはプラグインが裏で自動起動する)

2. **配置・起動方法 (Source)**:
   * `remote` (🌟推奨: パッケージをローカルにインストールせず、`uvx` を用いてオンザフライで起動・実行する。GitHub Packages から取得)
   * `local` (ローカルにクローン済みの本リポジトリ `chronos-gate` 内で直接実行・インストールする。ソースコードからビルド)
   *(※動作形態が `cli-hook` の場合は `local` のみ選択可能です。)*

3. **ポリシーファイル (`intents.yaml`) の配置場所**:
   * `local` (プロジェクト直下の `intents.yaml` を使用、または `intents.example.yaml` からコピーして作成する)
   * `global` (グローバル設定ディレクトリ `$HOME/.chronos-gate/intents.yaml` を使用、または作成する)
   * `custom` (ユーザーが指定する任意の絶対パスを使用する)

4. **起動ポート (Gateway Port)**:
   * `gateway-server` または `opencode-plugin` の場合に、起動ポート（デフォルト `9100` もしくは任意の指定ポート）を決定します。

5. **LLM 評価 (LiteLLM) の利用**:
   * `disabled` (決定論的ポリシーのみを使用する)
   * `enabled` (LLM による評価判定を有効化する。**この場合、AIエージェントは必ずユーザーに対して以下の情報を追加で質問（ask）して確定させてください（決して決め打ちで処理してはいけません）**:
     * **LLM モデル名** (例: `anthropic/claude-3-5-haiku` などのモデル名を選択または直接入力してもらう)
     * **LLM APIキー** (ユーザーにAPIキーの入力を求め、入力が完了するまで待機します。または「環境変数から取得する」ことを確認します)

6. **API 認証キーの設定**:
   * `auto` (セキュアなランダムトークンを自動生成する)
   * `custom` (ユーザーが指定した任意のトークンを設定する)
   *(※動作形態が `gateway-server` または `opencode-plugin` の場合のみ有効)*

---

### Phase 3: 自動セットアップスクリプトの実行と .env 出力
Phase 2 で確定したパラメータを引数に指定して、`scripts/bootstrap.sh` を実行します。
**※注意:** `dry-run` モードの場合は、本番環境への書き出しやファイルの作成は行わず、実行予定のコマンドや作成されるファイルの想定内容を出力するのみに留めてください。

#### デフォルト値と環境変数の出力先 (production モードのみ):
セットアップの設定および環境変数ファイル（`.env`）は、`production` モード時のみ、デフォルトで **`$HOME/.chronos-gate/.env`** 配下に作成・設定されます。

#### LLM用のAPIキーの反映 (production モードのみ):
`bootstrap.sh` 実行完了後、モードが `production` でかつLLM評価が有効（`enabled`）の場合は、ユーザーから取得した LLM API キーを上記の `$HOME/.chronos-gate/.env` に安全に書き出します。`dry-run` モードの場合は、ファイルへの書き出しは行わず、設定される予定の環境変数の内容を提示してください。

#### 設定される想定環境変数 (`$HOME/.chronos-gate/.env`):
```dotenv
# 1. ゲートウェイの起動ポート
MCP_GATEWAY_PORT=9100

# 2. プラグイン（送信側）およびゲートウェイ（受信側）の共通APIキーとJSONマッピング
# APIキーの命名は Phase 2 のポリシー配置場所 (global/custom) の挙動と整合させます
MCP_GATEWAY_API_KEY=your_global_or_custom_api_key_here
MCP_GATEWAY_API_KEYS_JSON={"global":"your_global_or_custom_api_key_here"}

# 3. ポリシーファイルの配置場所
MCP_GATEWAY_POLICY_PATH=~/.chronos-gate/intents.yaml

# 4. LLM 評価器用の設定 (LLM評価を利用する場合に設定)
CHRONOS_EVALUATOR_POLICY_PATH=~/.chronos-gate/intents.yaml
CHRONOS_EVALUATOR_API_KEY=your_llm_provider_api_key_here
CHRONOS_EVALUATOR_MODEL=anthropic/claude-haiku-4-5-20251001
```

#### 実行コマンド例 (グローバルポリシー・リモート取得使用時):
```bash
# <mode> には Phase 1 で確定した production または dry-run を指定する
./scripts/bootstrap.sh \
  --type evaluator \
  --mode <mode> \
  --target gateway-server \
  --source remote \
  --policy-path ~/.chronos-gate/intents.yaml \
  --gateway-port 9100
```

---

### Phase 4: 動作検証（疎通テスト）とクライアント設定の提示
セットアップ完了後、AIエージェントは以下の検証を行い、結果をユーザーに提示します。

1. **.env を読み込んでの疎通テスト**:
   * **`production` モードの場合**: 
     出力された `.env` ファイルの設定を読み込み、セキュリティ評価器の動作テストを行います。
     具体的には、以下のポリシー評価のテストを実行し、判定が正しく行われるかを確認します。
     * **`echo test` の評価**: 判定結果が **`allow`**（許可）となること。
     * **`rm test` の評価**: 判定結果が **`allow` 以外**（`deny` または要承認など）になること。
   * **`dry-run` モードの場合**: 
     実際のプロセス起動や評価テストは行いませんが、疎通確認のために実行すべきテストコマンド例（`echo test` -> `allow`, `rm test` -> `allow以外` の期待値）をシミュレーションとして提示します。
2. **クライアント向け設定スニペットの提示**:
   * `gateway-server` の場合: 各種エージェント（Claude Code 等）の `.env` や環境変数設定例。
   * `opencode-plugin` の場合: `opencode.json` / `oh-my-opencode.jsonc` の `plugins` セクションに追記すべき JSON テンプレート。
3. **最終サマリーの出力 (BLOCKING STEP)**:
   セットアップの全工程の終了時、AIエージェントは以下の情報を整理してユーザーに最終出力しなければなりません。
   * **生成されたファイル一覧** (作成された設定ファイル、`.env`、ポリシーファイルなどの絶対パス)
   * **編集されたファイル一覧** (既存の設定ファイルへの追記内容など)
   * **疎通テスト結果** (実際に実行された検証コマンドと、それに対する判定結果)
