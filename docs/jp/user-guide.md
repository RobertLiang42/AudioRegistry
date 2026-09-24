# ユーザーガイド

[日本語 README](README.md) · [简体中文](../cn/user-guide.md) · [English](../en/user-guide.md) · [インストールガイド（英語）](../en/installation.md)

`start.bat` をダブルクリックすると、プロジェクトの作成から音声処理まで順に進められます。`webui.bat` をダブルクリックすると、二つの WebUI を直接開けます。以下のコマンドは、各手順を個別に起動したり、オプションを指定したりする場合に使います。リポジトリのルートで PowerShell を開いて実行してください。二つのバッチファイルは、それぞれ `run.ps1` の `start` と `webui` を呼び出します。

## コマンドとオプション

| コマンド | 動作 |
| --- | --- |
| `start` | プロジェクトセンターを開き、必要に応じて話者分離と文字起こしを行ってから、二つの WebUI を開きます。 |
| `project` | プロジェクトの作成とデータベース管理のために、プロジェクトセンターだけを開きます。 |
| `process` | 既存プロジェクトに登録済みの音声を話者分離・文字起こしします。プロジェクトの作成や WebUI の起動は行いません。 |
| `webui` | プロジェクトの選択や処理を行わず、二つの WebUI を直接開きます。 |
| `webui1` | 単一プロジェクトのタイムライン確認画面だけを開きます。 |
| `webui2` | 複数プロジェクトのデータ構成画面だけを開きます。 |
| `language [zh-CN\|en-US\|ja-JP]` | 現在の UI 言語を表示するか、指定した UI 言語を保存します。 |
| `doctor` | 実行環境を確認します。 |

例：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 start
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 project
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 process
```

`run.ps1` は自分の場所からプロジェクトのディレクトリを特定するため、別のディレクトリから絶対パスで呼び出すこともできます。`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 --help` で組み込みヘルプを表示できます。個別のオプションを見るには、`start --help` のようにコマンドを `--help` の前に置きます。

グローバルオプション `--config PATH` は、コマンドの前に置いてメインの YAML 設定ファイルを指定します。既定値は `config/default.yaml` です。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 --config .\config\default.yaml doctor
```

| 対象コマンド | 引数 | 動作 |
| --- | --- | --- |
| `start`、`process` | `AUDIO` | 処理対象の選択画面を開かず、一つの音声ファイルを直接処理します。 |
| `start`、`process` | `--project NAME` | `AUDIO` と併用すると対象プロジェクトを指定します。`AUDIO` がない場合は、`start` のプロジェクト名を事前入力するか、`process` でそのプロジェクトを優先選択します。 |
| `start`、`process` | `--subtitle PATH` | 任意の字幕ファイルを指定します。選択画面で字幕を使う場合、選べるプロジェクトは一つだけです。 |
| `start`、`process` | `--start-padding SECONDS`、`--end-padding SECONDS` | 今回の処理に使う区間前後の余白を、0 以上の秒数で指定します。省略すると設定済みの値を使います。 |
| `start`、`process`、`webui1`、`webui` | `--language CODE` | 今回の ASR 言語を `auto`、`zh`、`en`、`ja` などに指定します。`language` コマンドで保存する UI 言語とは別です。 |
| `webui1`、`webui` | `AUDIO`、`--project NAME` | WebUI1 で登録済みの音声またはプロジェクトを開きます。`AUDIO` だけを指定すると、データベースからプロジェクトを特定します。 |
| `webui1`、`webui2` | `--port NUMBER` | 待ち受けポートを変更します。既定値はそれぞれ 8765 と 8766 です。 |
| `webui` | `--webui1-port NUMBER`、`--webui2-port NUMBER` | 二つの異なる待ち受けポートを指定します。既定値は 8765 と 8766 です。 |
| `webui1`、`webui2`、`webui` | `--no-open` | ローカルサーバーを起動しますが、ブラウザーのタブは自動で開きません。 |

例：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 process --project "Example Project"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 webui1 --project "Example Project"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 webui --webui1-port 8875 --webui2-port 8876 --no-open
```

## プロジェクトと処理の流れ

プロジェクトセンターには、単体・一括作成、作成待ちキュー、データベース管理がまとまっています。プロジェクトを作成すると、区間がなくても名前と音声の登録がすぐにデータベースへ保存され、下部の一覧が更新されます。WebUI1 のプロジェクトメニューからも同じ画面を開けます。

`start` では **次へ** をクリックすると、話者分離・文字起こしの画面に進みます。新しく作成したプロジェクトは、データベース一覧で最初から選択されています。そこで選択されている既存プロジェクトも含め、次の画面での初期選択として渡されます。選択を外すと初期選択から除外できます。処理画面では選択を変更したり、何も選ばなかったり、**スキップ** を選んで処理せずに二つの WebUI へ進んだりできます。有効な登録音声があるプロジェクトだけを処理できます。

処理を行った場合、`start` は最後に処理したプロジェクトを WebUI1 に渡します。処理を行わなかった場合は、プロジェクトセンターで最後に選択されていたプロジェクトを渡し、選択がなければ初期プロジェクトを指定しません。WebUI2 には、プロジェクトセンターで選択されたすべてのプロジェクト名と、実際に処理したプロジェクト名を渡します。**次へ** または **スキップ** を使わずにいずれかの画面を閉じると、`start` はキャンセルされます。

`start AUDIO [--project NAME]` を指定すると、二つの選択画面を省略します。必要ならプロジェクトを作成して音声を登録し、音声を処理してから二つの WebUI を開きます。既存プロジェクトでは、その音声がすでに登録されている必要があります。`--project` を省略して新規作成する場合、音声ファイルの拡張子を除いた名前がプロジェクト名になります。

`process` は既存プロジェクトに登録済みの音声だけを処理します。プロジェクトの作成や WebUI の起動は行いません。`AUDIO` を省略すると処理対象の選択画面を開きます。`AUDIO` を指定する場合、その音声は既存プロジェクトに登録済みである必要があります。登録情報からプロジェクトを特定するか、`--project` で指定できます。処理には二つのダウンロード済みモデルが必要です。[インストールガイド（英語）](../en/installation.md)を参照してください。

## 確認とデータ構成

WebUI1 は単一プロジェクトのタイムライン編集画面です。時間座標、話者、文字起こし、タグ、メモの確認と編集に加え、音声プレビュー、再文字起こし、字幕やクリップの出力ができます。既存プロジェクトの編集内容は、**保存** をクリックするまでページ内に保持されます。プロジェクトの更新回数は、外部での変更を検出するために使います。

WebUI2 では複数プロジェクトのデータを組み合わせられます。音声のバリエーションとオフセット、絞り込み、クリップ処理、リスト出力、表計算ファイルへの出力に対応します。生成物は既定では Git の管理対象外である `output/` に保存され、リストは `output/asr_opt/slicer_opt.list` に出力されます。

元の音声ファイルは元の場所に残ります。ローカルのデータベースは既定で `data/audio-registry.sqlite3` です。ソースを更新・整理する際に削除しないでください。

## 言語と設定

言語の選択が保存されていない場合、画面は対応するブラウザーまたはシステムの言語を使い、対応していなければ英語になります。UI 言語を保存するコマンドは次のとおりです。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 language zh-CN
```

英語または日本語を選ぶには、`zh-CN` を `en-US` または `ja-JP` に置き換えてください。アプリの標準設定は `config/default.yaml` にあります。端末固有の設定は、Git の管理対象外である `config/default.local.yaml` に保存してください。Python、FFmpeg、モデルの設定については[インストールガイド（英語）](../en/installation.md)を参照してください。
