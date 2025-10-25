# 引き継ぎ書（エスペラント会話のリアルタイム文字起こし）

本書は、Google Meet/Zoom の会議音声を PC 内で取り込み、Speechmatics Realtime にストリーミングしてエスペラント語の文字起こしを行うための、セットアップ〜運用〜トラブルシュートまでを網羅した引き継ぎ資料です。後続の方が迷わず運用できるよう、実際に起きたエラーと対処も記載しています。

---

## 1. 現状と成果物（要約）

- リアルタイム文字起こしは正常稼働済み。
  - ログ例（INFO）: `Recognition started.` の後に `Final: Ĉu vi aŭdis?` など確定文が流れる。
- 実装の要点:
  - Audio 取り込み: `sounddevice`（PipeWire/BlackHole/VoiceMeeter 等の仮想オーディオ入力）
  - STT バックエンド: Speechmatics をメイン、Whisper/Vosk を切り替え可能
  - JWT 認証: API キーからの自動 JWT 取得を実装（mp.speechmatics.com v1）
  - Zoom CC API: 送出器あり（Meet時は無効化）
  - ログ: `logs/meet-session.log` にタイムスタンプ付きで確定文を追記

---

## 0. 最短クイックチェック（5分）

1) `.venv311` を有効化 → `pip install -r requirements.txt` 済み確認。
2) `python -m transcriber.cli --list-devices` で仮想入力デバイス番号を確認（例: pipewire = 8）。
3) `.env` を設定：`SPEECHMATICS_API_KEY`、`SPEECHMATICS_CONNECTION_URL`（EUは `wss://eu2.rt.speechmatics.com/v2`）、`AUDIO_DEVICE_INDEX`。
4) `python -m transcriber.cli --show-config` で `connection_url` と `audio.sample_rate=16000` を確認。
5) `python -m transcriber.cli --backend=speechmatics --log-level=INFO` で起動。`Recognition started.` → `Final:` が出ればOK。

---

## 2. ディレクトリと主ファイル

- `transcriber/` 文字起こしコア
  - `audio.py` … PCM16 16kHz モノラルの非同期チャンク入力
  - `pipeline.py` … Audio→ASR→出力（Zoom/ログ）をオーケストレーション
  - `zoom_caption.py` … Zoom Closed Caption API 送信器
  - `asr/` … バックエンド切替層
    - `speechmatics_backend.py` … Realtime v2 WebSocket クライアント（本番）
    - `whisper_backend.py` … faster-whisper（GPU/Mシリーズ向け）
    - `vosk_backend.py` … Vosk（完全オフライン）
  - `cli.py` … コマンドライン実行（デバイス列挙/設定表示/起動）
- 設定ファイル
  - `.env`（運用用, 秘匿）／`.env.example`（雛形）
- ドキュメント
  - `README.md`（セットアップ概要）
  - 本書（詳細運用ガイド）

---

## 3. セットアップ手順（初回）

1) Python 環境
- Python 3.11 の仮想環境を作成（本番では `.venv311` を使用）
  ```bash
  python3.11 -m venv .venv311
  source .venv311/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
  ```

2) 音声ルーティング
- OS に応じた仮想オーディオを準備（例）
  - Linux: PipeWire/PulseAudio の loopback
  - Windows: VB-Audio / VoiceMeeter
  - macOS: BlackHole
- Meet/Zoom の出力を仮想入力へループバック。`--list-devices` でデバイス名を確認し、`.env` の `AUDIO_DEVICE_INDEX` に設定。

補足（OS別の一例）
- Linux（PipeWire）：`pw-loopback` を使い、アプリ出力→ループバック→デフォルト入力を接続。
- Windows：VoiceMeeter Banana で Zoom/ブラウザ出力を仮想入力へルーティングし、同時にスピーカーへモニタ。
- macOS：BlackHole（2ch）と複合デバイスを作成し、会議アプリ出力に指定。

3) Speechmatics の準備
- Portal で Realtime が有効であることを確認し、**長期 API キー**を取得（キー文字列は rt- で始まらない場合もある）。
- **リージョン**を確認（EU/US）。本番では EU: `eu2` を使用。

4) `.env` を作成
```ini
TRANSCRIPTION_BACKEND=speechmatics
SPEECHMATICS_API_KEY=<長期APIキー>
SPEECHMATICS_CONNECTION_URL=wss://eu2.rt.speechmatics.com/v2  # US契約なら us2
SPEECHMATICS_LANGUAGE=eo
AUDIO_DEVICE_INDEX=8        # 例: pipewire
ZOOM_CC_ENABLED=false       # Meet利用のため
TRANSCRIPT_LOG_ENABLED=true
TRANSCRIPT_LOG_PATH=logs/meet-session.log
```

---

## 4. 実行手順

1) 設定確認
```bash
.venv311/bin/python -m transcriber.cli --show-config
```
`speechmatics.connection_url` と `audio.sample_rate=16000` を確認。

2) 起動（Speechmatics）
```bash
.venv311/bin/python -m transcriber.cli --backend=speechmatics --log-level=INFO
```
正常時:
- `Recognition started.` → `Final: ...` が出力され、`logs/meet-session.log` に追記されます。

Sanity テスト（任意）
- テスト用に「Ĉu vi aŭdis?」など短いフレーズを発話し、`Final:` 行がログへ追記されることを確認。

3) バックアップ起動（オフライン Vosk）
```bash
# 事前に .env に VOSK_MODEL_PATH を設定
.venv311/bin/python -m transcriber.cli --backend=vosk --log-file logs/offline.log
```

---

## 5. 実装のポイント（Speechmatics Realtime v2）

- 認証: **APIキー→短期JWTの自動取得**に対応
  - `transcriber/asr/speechmatics_backend.py` で管理プラットフォーム `https://mp.speechmatics.com/v1/api_keys?type=rt` に POST し、`key_value`（短期トークン）を取得。
  - 取得トークンは `Authorization: Bearer <JWT>` で WS に付与。
- 接続 URL: `wss://<region>.rt.speechmatics.com/v2/<language>` 形式
  - 実装で言語サフィックス（`/eo` 等）を補完。
- プロトコルメッセージ
  - StartRecognition を JSON で送信
  - `RecognitionStarted` を受けてから音声送信（非同期イベント待機）
  - 受信は `AddPartialTranscript` / `AddTranscript`（`metadata.transcript`）
- 互換対応
  - `enable_punctuation` はサーバ schema により拒否されたため送信しない（内部で自動句読点）
  - websockets v15 のヘッダーは `additional_headers` を使用
  - Pydantic の URL バリデーションは `wss` を許容するため `str` に変更

---

## 6. Google Meet/Zoom の使い分け

- Google Meet
  - 仮想オーディオ（例: pipewire）に会議音声を流し、`AUDIO_DEVICE_INDEX` で指定
  - Meet 画面への字幕重畳は本実装では未対応（必要なら Electron/OBS でオーバーレイを追加）
- Zoom
  - Zoom 画面内に字幕を出したい場合は、`ZOOM_CC_ENABLED=true` と `ZOOM_CC_POST_URL` を設定して起動
  - CC URL の取得（ホスト）：会議内 → 字幕（CC）を有効化 → 「サードパーティの字幕サービスを使用」→ 生成された URL をコピー → `.env` の `ZOOM_CC_POST_URL` に貼付（`seq` はプログラム側で自動付与）。

---

## 7. トラブルシュート（症状 → 原因 → 対処）

- `404 path not found`（JWT発行時）
  - 原因: 認可エンドポイントのパス違い
  - 対処: 管理プラットフォーム `https://mp.speechmatics.com/v1/api_keys?type=rt` で発行（実装済み）

- `1003 unsupported data`（WS 直後）
  - 原因: StartRecognition の schema 不一致、またはリージョンURL/言語サフィックス不足
  - 対処: StartRecognition 形式に統一、`/v2/<language>` を付与（実装済み）

- `401/403 Unauthorized`
  - 原因: APIキーがRealtime権限なし/無効
  - 対処: Portal で Realtime 有効化とキーの再取得。リージョン（eu2/us2）を確認

- `Speechmatics error: {... "enable_punctuation" is not allowed}`
  - 原因: サーバ schema と不一致
  - 対処: 送信パラメータから `enable_punctuation` を削除（実装済み）

- 音声が無音/誤ったデバイス
  - 原因: デバイス選択ミス
  - 対処: `--list-devices` で確認し `.env` の `AUDIO_DEVICE_INDEX` を修正

- `Recognition did not start in time.`（内部タイムアウト）
  - 原因: StartRecognition 後の `RecognitionStarted` が届かない
  - 対処: URL/リージョン/言語サフィックス、APIキーの権限、ネットワーク（企業プロキシ/ファイアウォール）を確認

- `429 Too Many Requests` / レート超過
  - 原因: 短時間の連続接続/切断
  - 対処: 5〜10秒の待機後に再試行。連続テスト時は間隔を空ける

- TLS/プロキシ関連の失敗
  - 原因: 企業プロキシや TLS インスペクション
  - 対処: `HTTPS_PROXY`/`HTTP_PROXY` の設定、`eu2.rt.speechmatics.com` と `mp.speechmatics.com` への 443 通信許可

---

## 8. セキュリティと運用

- `.env` やログに機微情報を残さない
  - `.gitignore` に `.env` と `logs/` を登録済み
  - キーの貼付や共有は厳禁、必要ならキーのローテーション
- 参加者への通知
  - 録音・字幕の実施を事前に周知
- コスト/クォータ
  - Speechmatics Pro 従量: 例 `$0.24/時`（90分 ≒ $0.36 ≒ 約55円、為替次第）
 - ログ保全方針
   - `logs/` の保存期間・アクセス権・暗号化（必要に応じて）をチームポリシーで定義

---

## 9. 拡張計画（希望があれば対応）

- カスタム辞書登録 UI/設定の追加（固有名詞の誤認を削減）
- Meet 向け字幕オーバーレイ（Electron/OBS）
- Whisper バックエンドの最適化（GPU/Mシリーズで sub-sec 遅延）
- 自動リトライ・再接続の強化、メトリクス収集/監視
- 翻訳（eo→ja/en）の連結表示

---

## 10. コマンド チートシート

```bash
# 仮想環境
source .venv311/bin/activate

# デバイス列挙
python -m transcriber.cli --list-devices

# 設定確認
python -m transcriber.cli --show-config

# 起動（Speechmatics）
python -m transcriber.cli --backend=speechmatics --log-level=INFO

# 起動（Vosk オフライン）
python -m transcriber.cli --backend=vosk --log-file logs/offline.log

# デバッグログ
python -m transcriber.cli --backend=speechmatics --log-level=DEBUG
```

---

## 付記: 変更履歴（主要な実装変更）

- WebSockets ヘッダ `extra_headers` → `additional_headers`（websockets 15系）
- Realtime エンドポイントを `wss://eu2.rt.speechmatics.com/v2` に更新
- Pydantic の `HttpUrl` 厳格チェックを緩和（`wss` 許容）
- ZoomCaptionConfig の URL 型を `str` に変更
- API キー → JWT 自動取得を実装（`mp.speechmatics.com/v1/api_keys?type=rt`）
- StartRecognition 形式に更新／`RecognitionStarted` 待機を追加
- `enable_punctuation` 送信を削除（schema 不一致回避）

以上。
