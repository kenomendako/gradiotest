# batch_importer.py (Phase 1 Temporary Stub)

import sys
import os

def main():
    print("="*60)
    print("!!! [機能停止中] このバッチインポーターは現在使用できません。!!!")
    print("    記憶システムがMemOSからCogneeに移行中のため、")
    print("    このスクリプトはフェーズ2で新しい仕様に合わせて更新される予定です。")
    print("="*60)
    if os.name == "nt":
        os.system("pause")
    else:
        input("続行するにはEnterキーを押してください...")
    sys.exit(1)

if __name__ == "__main__":
    main()
