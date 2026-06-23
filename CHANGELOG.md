# Changelog

## [1.1.0](https://github.com/yohi/chronos-gate/compare/v1.0.0...v1.1.0) (2026-06-23)


### Features

* **.coderabbit.yaml:** 削除された `.coderabbit.yaml` ファイルを追加しました。 ([c3a82ea](https://github.com/yohi/chronos-gate/commit/c3a82ea995656fb065113ec6881d6ade64d33890))
* initial chronos-gate separation from chronos-graph ([6765fba](https://github.com/yohi/chronos-gate/commit/6765fbadce77b64e96897ac06d68869f3043f171))
* initial chronos-gate separation from chronos-graph ([0ac1b44](https://github.com/yohi/chronos-gate/commit/0ac1b443f180821bd3e48e99c8372efba0712e9a))
* npmパッケージ名を@yohi/chronos-gateへ変更 ([e0f1e81](https://github.com/yohi/chronos-gate/commit/e0f1e8174d2cf04aac977c48593f5430511e6753))
* npmパッケージ名を@yohi/chronos-gateへ変更 ([b3894f4](https://github.com/yohi/chronos-gate/commit/b3894f422a54ad0d12ed88bc9fe172d79f0b1422))


### Bug Fixes

* approval エンドポイントの approval_id 未定義エラーを修正 ([5b11fd8](https://github.com/yohi/chronos-gate/commit/5b11fd81ec1dc76897dbd74dec648005b85462ca))
* approval エンドポイントの認可判定を修正 ([0ca15ca](https://github.com/yohi/chronos-gate/commit/0ca15ca55072a762723c323185c0ce7b45411d6e))
* CancelledError発生時のフューチャー未解決ハングを修正 ([32a2dd4](https://github.com/yohi/chronos-gate/commit/32a2dd4dd0ca199b7bb504f3ef21166dc5f07061))
* CHRONOS_EVALUATOR_FALLBACKの未検証値による起動クラッシュを防止 ([2c1a2b7](https://github.com/yohi/chronos-gate/commit/2c1a2b748a1dad99661ab473f2beaa362aa386a2))
* CI check失敗を修正 ([3ee4887](https://github.com/yohi/chronos-gate/commit/3ee488712863ca7d9644aabbef5ccd7f5fe54b27))
* **ci:** release workflow の setup-python pin を修正 ([0ea7a88](https://github.com/yohi/chronos-gate/commit/0ea7a886329949dee9ce59afa2e0c154eb6de14b))
* **ci:** release workflow の setup-python pin を修正 ([bd8088b](https://github.com/yohi/chronos-gate/commit/bd8088b5642aaacdd69c0c11eb551590a964e09a))
* CIチェック失敗の修正 ([9c23fb6](https://github.com/yohi/chronos-gate/commit/9c23fb6d546b8d20d6e18731f22224c877f664e6))
* **gateway:** lint警告(B904, I001)の修正 ([0455f03](https://github.com/yohi/chronos-gate/commit/0455f03f049d8d53e6ab1cf181e275e4177b2e42))
* **gate:** 不正なフォールバック値を 'ask' へ変更しセキュリティを改善 ([ed8356d](https://github.com/yohi/chronos-gate/commit/ed8356d5215c14c4e2ce52a480d67840d0a5f237))
* Git URLとホームディレクトリの安全性を向上 ([41efc80](https://github.com/yohi/chronos-gate/commit/41efc80f690953c1bfe332961309576adb1e3271))
* LLMフォールバックのデフォルトを安全に変更 ([f6fdfee](https://github.com/yohi/chronos-gate/commit/f6fdfee3bd18f15b3c79ecf876878501b4ba93ee))
* **plugin:** permission.asked ハンドラのレジストリ追跡とエラーハンドリングを修正 ([65adcef](https://github.com/yohi/chronos-gate/commit/65adcef560c816fae05bc843d3ca86ecad4f0b91))
* **plugin:** TUIの権限要求をChronosGate経由で応答 ([8ccce13](https://github.com/yohi/chronos-gate/commit/8ccce1344984cbf2ee0e02bfc55e12625701d15a))
* **plugin:** TUIの権限要求をChronosGate経由で応答 ([b4bac01](https://github.com/yohi/chronos-gate/commit/b4bac013c1e7ca10a33692ae515e131093ebbd0f))
* pluginでの'ask'判定の格下げを修正し確認プロンプトを正常化 ([12b00f0](https://github.com/yohi/chronos-gate/commit/12b00f06bcf70fd4321f2d1f974c5ed131f1df44))
* PR [#1](https://github.com/yohi/chronos-gate/issues/1) のCI/セキュリティ/コード品質チェック失敗を修正 ([aaafcc5](https://github.com/yohi/chronos-gate/commit/aaafcc52256a115fab40a675d96d67a5de111b5e))
* ruff check通過 - 未使用インポート削除 ([f55a577](https://github.com/yohi/chronos-gate/commit/f55a577c617a54a545bcc814227c0909bd63a4e7))
* ruff formatとSonarCloud警告を修正 ([b1dbb02](https://github.com/yohi/chronos-gate/commit/b1dbb029e0f7ad36e8e9e43f130edf44f072a025))
* SonarCloud残りの警告を修正 ([10c37f0](https://github.com/yohi/chronos-gate/commit/10c37f0c0a33a8ef16f544ebc81943c23432feef))
* twine認証のユーザー名を標準形に変更 ([5b3907d](https://github.com/yohi/chronos-gate/commit/5b3907d362b80f2e351f93b8b0c69ec92a749892))
* uvx起動時のハードコードSHAをmasterブランチ参照に変更 ([5debf95](https://github.com/yohi/chronos-gate/commit/5debf95e958455cb664ada3698edb9eb5698f919))
* **workflow:** SemgrepによるAPIキー誤検知を nosemgrep で抑制 ([9d4b2b3](https://github.com/yohi/chronos-gate/commit/9d4b2b38594ffff40f39a05cd8721af9366a7c57))
* **workflow:** SemgrepによるAPIキー誤検知を回避するため別バージョンのコミットSHAを使用 ([b9fd5a3](https://github.com/yohi/chronos-gate/commit/b9fd5a3fc1b47996412f6f67eacdee145ef89ef6))
* **workflow:** SemgrepのAPIキー誤検知を回避するためSHAピン留めからバージョンタグ指定([@v8](https://github.com/v8).2.0)に変更 ([78f3357](https://github.com/yohi/chronos-gate/commit/78f3357dc51d8edb2eac10ec34c3dff71cd26605))
* **workflow:** Semgrep誤検知をnosemgrepで抑制しSHAピン留めを維持 ([5e81d0a](https://github.com/yohi/chronos-gate/commit/5e81d0ad200c03f1f83130d2d15f7b77e74e77bc))
* **workflow:** SonarSourceアクションの正しい v4.1.0 コミットSHAを指定 ([85d502b](https://github.com/yohi/chronos-gate/commit/85d502b2b8ca706131899772b7e9800fb0ee5796))
* **workflow:** SonarSourceアクションを v8.2.0 (SHA固定) にアップグレード ([6a213aa](https://github.com/yohi/chronos-gate/commit/6a213aa10cda6462edc81770a549da6e173b174f))
* **workflow:** SonarSourceアクションをSHAピン留めに戻し、供給チェーンセキュリティを強化 ([0305b72](https://github.com/yohi/chronos-gate/commit/0305b72c0c07e8bf57c1d88fc9b4cd329093b40b))
* キャンセル時のreasonパラメータ転送を修正 ([d375b60](https://github.com/yohi/chronos-gate/commit/d375b6041b7e86aab6d763245c8726f4721030f0))
* サーバーモードのCHRONOS_EVALUATOR_FALLBACKデフォルトをaskに統一 ([6599dd0](https://github.com/yohi/chronos-gate/commit/6599dd03a3163729451ea6395ae01b85d68a4674))
* セッションIDの誤マスクと承認者ロール検証を修正 ([96be7f9](https://github.com/yohi/chronos-gate/commit/96be7f9994805e1e42c26c495c1f81d7534e5374))
* ポリシーエンジンの型安全性を強化 ([0c0f4ba](https://github.com/yohi/chronos-gate/commit/0c0f4bae78c4a9940c2ceb4f1cf47513105ed7be))
