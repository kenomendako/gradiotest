---
---
# **CLI連携・実装の教訓：`subprocess`と文字コードとの戦いの記録**

このドキュメントは、Pythonアプリケーションから外部のコマンドラインインターフェース（CLI）、特にWindows環境下でNode.js製の`@google/gemini-cli`を呼び出す際に、我々が直面した一連の技術的な課題とその解決策を記録したものである。

## **【問題の核心】Pythonの`subprocess`とWindows CLIの間の「4つの壁」**

我々の最終的な目標は、Pythonから`gemini.cmd`を安定して呼び出すことだった。しかし、その過程で以下の4つの根深い問題に直面した。

### **壁1：`NameError` - `import`文はどこにあるべきか？**

-   **問題:** `subprocess`を呼び出すコードを記述したにも関わらず、`NameError: name 'subprocess' is not defined`というエラーが発生した。
-   **原因:** `import subprocess`文が、ファイルの先頭ではなく、関数定義の直前など、不適切な位置に記述されていた。
-   **教訓:** **`import`文は、必ずファイルの先頭にまとめて記述する。** これはPythonのコーディング規約（PEP 8）の基本であり、スクリプト全体のスコープと可読性を保つための絶対的なルールである。JulesのようなAIアシスタントも、この規約を前提としてコードを解釈する。

### **壁2：`TypeError` - `genai.Client`は`transport`引数を取らない**

-   **問題:** 過去のネットワークエラー対策として`genai.Client(transport="rest")`としていたコードが、`TypeError: Client.__init__() got an unexpected keyword argument 'transport'`を発生させた。
-   **原因:** プロジェクトの規約である`google-genai`SDKの正しい初期化方法に、`transport`引数は含まれていなかった。これは、過去の別ライブラリの仕様や、一時的な対策が残ってしまった結果である。
-   **教訓:** **プロジェクトの技術選定に関するガイドライン（`AI_DEVELOPMENT_GUIDELINES.md`）は絶対である。** 予期せぬ`TypeError`に遭遇した場合、まずは自分たちが定めた規約に立ち返り、APIの基本的な呼び出し方から再確認すること。

### **壁3：`CalledProcessError`と文字化け - Windowsのエンコーディング地獄**

-   **問題:** `subprocess.run`に`encoding='utf-8'`や`encoding=locale.getpreferredencoding()`を指定しても、CLIからの日本語の応答が文字化け（`R}h C܂B`など）した。
-   **原因:** 呼び出し先の`gemini.cmd`が内部で実行するNode.jsプロセスが、Python側の`encoding`指定を無視し、Windowsのデフォルトエンコーディング（多くは`cp932`/`Shift_JIS`）で標準出力に書き込んでいたため。Python側はUTF-8として解釈しようとするため、エンコーディングのミスマッチが発生した。
-   **教訓:** **外部プロセスの出力エンコーディングは、呼び出し側からは制御できない場合がある。**
    -   `NODE_OPTIONS`環境変数で出力エンコーディングを強制するアプローチも、Node.jsのセキュリティポリシーによりブロックされた。
    -   最終的な解決策は、`subprocess.run`では`text=True`を指定せず、**生のバイト列として出力を受け取り、それをPython側で明示的に正しいエンコーディング（この場合は`'cp932'`または`'utf-8'`と`errors='ignore'`）でデコードする**ことだった。

### **壁4：`Command line too long` - Windowsコマンドライン長の制限**

-   **問題:** 会話履歴が長くなるにつれて、プロンプトをJSON化した巨大な文字列をコマンドライン引数（`-p`）で渡そうとすると、「コマンドラインが長すぎます」というエラーで`subprocess`が失敗した。
-   **原因:** Windowsの`cmd.exe`には、単一のコマンドとして渡せる文字列長に約8191文字という物理的な上限が存在するため。
-   **教訓:** **巨大なデータを外部コマンドに渡す際は、コマンドライン引数を使ってはいけない。**
    -   `--prompt_file`のような引数がコマンドに用意されていればそれを使うのが理想だが、`gemini`コマンドには存在しなかった。
    -   最も確実で移植性の高い解決策は、**データを一時ファイルに書き出し、それを標準入力（`stdin`）としてリダイレクトする**方法である。これにより、データ長の制限は事実上なくなり、エンコーディングもファイル側で`utf-8`に統一できる。

## **【最終的なコードパターン】堅牢な`subprocess`呼び出し**

以上の教訓をすべて反映した、Windows環境で外部CLIを安全に呼び出すための最終的なPythonコードパターンは以下の通りとなる。

```python
import subprocess
import tempfile
import os
import json

def call_external_cli(command_path, prompt_json_data):
    temp_f = None
    try:
        # 1. 長いプロンプトをUTF-8で一時ファイルに書き出す
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as temp_f:
            json.dump(prompt_json_data, temp_f, ensure_ascii=False, indent=2)
            temp_file_path = temp_f.name

        # 2. ファイルを標準入力としてリダイレクトしてコマンドを実行
        with open(temp_file_path, 'r', encoding='utf-8') as stdin_file:
            result = subprocess.run(
                [command_path],         # 実行ファイルのパス
                stdin=stdin_file,       # stdinリダイレクト
                capture_output=True,    # 出力をキャプチャ
                check=True              # エラーコードで例外を発生
            )

        # 3. 結果のバイト列を、想定されるエンコーディングでデコード
        # CLIの出力がUTF-8であることを期待する
        stdout_str = result.stdout.decode('utf-8', errors='ignore')
        return stdout_str.strip(), None

    except subprocess.CalledProcessError as e:
        # エラー出力も同様にデコード
        stderr_str = e.stderr.decode('utf-8', errors='ignore')
        error_message = f"CLI Error (Code {e.returncode}): {stderr_str.strip()}"
        return None, error_message
    except Exception as e:
        return None, f"An unexpected error occurred: {e}"
    finally:
        # 4. 一時ファイルを確実に削除
        if temp_f and os.path.exists(temp_f.name):
            os.remove(temp_f.name)
```
---
