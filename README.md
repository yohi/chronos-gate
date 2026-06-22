# ChronosGate 🛡️

**Universal security evaluator gateway for AI agent tool calls**

[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

ChronosGate は、AI エージェントのツール呼び出しを **deterministic（決定論的ポリシー: `intents.yaml`）** + **LLM（LiteLLM 経由）** の二層で多面的に検証・判定する防壁です。

このリポジトリは [ChronosGraph](https://github.com/yohi/chronos-graph) エコシステムの一部として独立したリポジトリです。`chronos-gate` は `chronos-graph` に依存し、セキュリティ評価機能を提供します。

---

## インストール

```bash
# Python パッケージ
uv pip install "chronos-gate @ git+https://github.com/yohi/chronos-gate.git"

# OpenCode プラグイン
npm install @yohi/chronos-gate
```

## クイックスタート

### CLI Hook

```bash
chronos-gate evaluate --json-io --policy-path /path/to/intents.yaml
```

### HTTP サーバー

```bash
chronos-gate run
```

`POST /evaluate` でツール呼び出しを評価します。

### OpenCode プラグイン

`~/.config/opencode/opencode.json`:

```json
{
  "plugins": [
    {
      "name": "chronos-safety-gate",
      "path": "./node_modules/@yohi/chronos-gate",
      "enabled": true
    }
  ]
}
```

## 設定

主要な環境変数:

| 環境変数 | 説明 |
|---|---|
| `CHRONOS_EVALUATOR_API_KEY` | LLM 評価用 API キー（未設定時は LLM 評価をスキップ） |
| `CHRONOS_EVALUATOR_MODEL` | LiteLLM モデル識別子 |
| `CHRONOS_EVALUATOR_POLICY_PATH` | `intents.yaml` のパス（必須） |
| `CHRONOS_EVALUATOR_FALLBACK` | LLM 未構成時の挙動（`allow` / `ask`） |
| `CHRONOS_DASHBOARD_URL` | 記憶検索用の ChronosGraph dashboard URL（任意） |

詳細は [ChronosGraph README](https://github.com/yohi/chronos-graph#universal-evaluator-mcp-gateway) を参照してください。

## ライセンス

MIT License — [LICENSE](LICENSE)
