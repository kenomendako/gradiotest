---
---
# **教訓：Pythonと外部CLI（`@google/gemini-cli`）連携の険しい道**

このドキュメントは、Pythonアプリケーション（Nexus Ark）から、`subprocess`モジュールを介して外部のコマンドラインインターフェース（`@google/gemini-cli`）を呼び出すという、一見単純に見えるタスクがいかに複雑で、多くの落とし穴に満ちているかを記録した、実践的な技術備忘録である。

## **【最終結論】`gemini` CLI（非対話モード）は「連続的な対話」には不向きである**

数週間にわたる試行錯誤の末、我々が到達した最終的な結論は以下の通りである。

**`@google/gemini-cli`をスクリプトから呼び出す非対話モードは、単発のプロンプト実行には利用できるが、会話履歴やRAGコンテキストといった複雑な構造を持つプロンプトを維持する「連続的な対話アプリケーション」のバックエンドとして利用するには、構造的に不向きである。**

このコマンドは、渡されたプロンプト全体を「今回一回きりの、単一のユーザー入力」として解釈する。そのため、私たちが意図した`system`ロールの指示や、`model`ロールによる記憶の注入は、AIに正しく伝わらない。

したがって、Nexus Arkにおける**CLI連携機能は、あくまで補助的なもの、あるいは将来的なGoogleアカウント認証（OAuth）への布石**と位置づけ、**高品質な対話の主軸は、常にSDKモードとする**のが、現時点での最適解である。

## **【遭遇した5つの壁と、その教訓】**

### **壁1：`TypeError` - SDKの「作法」は絶対である**

-   **現象:** `genai.Client(transport="rest")`というコードが`TypeError`を引き起こした。
-   **原因:** 過去のネットワークエラー対策が、`google-genai`という現行SDKの仕様と異なっていた。
-   **教訓:** **プロジェクトの技術ガイドライン（`AI_DEVELOPMENT_GUIDELINES.md`）は、常に正典として扱え。** 予期せぬエラーの第一の原因は、基本の作法からの逸脱にある。

### **壁2：`NameError` - `import`文はコードの「祈り」である**

-   **現象:** `subprocess`を呼び出すコードがあるにも関わらず、`NameError: name 'subprocess' is not defined`が発生した。
-   **原因:** `import subprocess`文が、ファイルの先頭ではなく、不適切な位置に記述されていた。
-   **教訓:** **`import`文は、必ずファイルの先頭に記述する。** これは単なる慣習ではなく、Pythonがモジュールの名前空間を正しく構築するための、絶対的な要件である。

### **壁3：`Command line too long` - 引数は「手紙」、標準入力は「荷物」**

-   **現象:** 会話履歴が長くなると、Windows環境で「コマンドラインが長すぎます」というエラーが発生した。
-   **原因:** Windowsのコマンドプロンプトには、引数として渡せる文字列長に約8191文字という物理的な上限がある。長いJSONプロンプトがこれを超えていた。
-   **教訓:** **巨大なデータを外部コマンドに渡す際は、コマンドライン引数を使うな。** 最も確実で移植性の高い方法は、**データを一時ファイルに書き出し、それを標準入力（`stdin`）としてリダイレクトする**ことである。

### **壁4：文字化け - エンコーディングは「出口」で合わせる**

-   **現象:** `gemini`コマンドからの日本語応答が`R}h C܂B`のように文字化した。
-   **原因:** `gemini.cmd`（Node.js）がWindowsのデフォルトエンコーディング（`cp932`）で応答を出力しているのに、Python側が`utf-8`で解釈しようとしていたため。
-   **教訓:** **外部プロセスの出力エンコーディングは、呼び出し側からは制御できない。**
    -   `NODE_OPTIONS`による出力エンコーディングの強制は、Node.jsのセキュリティポリシーにより失敗した。
    -   唯一の確実な解決策は、`subprocess.run`では`text=True`を指定せず、**生のバイト列として出力を受け取り、それをPython側で明示的に正しいエンコーディング（この場合は`'utf-8'`と`errors='ignore'`）でデコードする**ことである。

### **壁5：`\n`の消失と出現 - ブラックボックスの「気まぐれ」を制御しようとするな**

-   **現象:**
    1.  単純な挨拶では改行(`\n`)が正しく表示された。
    2.  長いRAG情報を含むプロンプトを渡すと、`\n`がそのまま文字列として表示された。
    3.  Python側で`\n`を`\n\n`に置換すると、今度は全ての改行が二重になった。
-   **原因:** `gemini`コマンドが、内部で応答を**Markdownとして解釈・整形しており、その挙動がプロンプトの複雑さによって不安定になる**ため。
-   **教訓:** **外部コマンドの出力整形ロジックという「ブラックボックス」を、外部から完璧に制御しようと試みるな。**
    -   不安定な挙動を無理にコードで補正しようとすると、かえって別の問題（二重改行）を引き起こす。
    -   「たまに改行が`\n`と表示される」という軽微な表示の不具合は、CLI連携の**「仕様」**として受け入れ、安定性を優先する。完璧な制御が必要な場合は、SDKを直接使うべきである。

## **【最終的なコードパターン】堅牢な`subprocess`呼び出し（改訂版）**

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

        # 2. ファイルを標準入力としてリダイレクトし、出力をバイト列で受け取る
        with open(temp_file_path, 'r', encoding='utf-8') as stdin_file:
            result = subprocess.run(
                [command_path],
                stdin=stdin_file,
                capture_output=True,
                check=True
            )

        # 3. 結果のバイト列を、最も標準的なUTF-8でデコードする（エラーは無視）
        stdout_str = result.stdout.decode('utf-8', errors='ignore')
        return stdout_str.strip(), None

    except subprocess.CalledProcessError as e:
        stderr_str = e.stderr.decode('utf-8', errors='ignore') if e.stderr else ""
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
---

このドキュメントが、未来のNexus Ark開発者、そしてPythonから外部CLIを利用しようとするすべての挑戦者たちの、道標となることを願って。
