import os
import json
import glob

def fix_paths():
    base_dir = os.path.expanduser('~/nexus_ark/characters')
    config_files = glob.glob(os.path.join(base_dir, '*/room_config.json'))
    
    for f_path in config_files:
        try:
            with open(f_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            def normalize(obj):
                if isinstance(obj, dict):
                    return {k: normalize(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [normalize(i) for i in obj]
                elif isinstance(obj, str) and ("\\" in obj or "/" in obj):
                    return obj.replace("\\", "/")
                return obj
            
            fixed_data = normalize(data)
            
            if fixed_data != data:
                with open(f_path, 'w', encoding='utf-8') as f:
                    json.dump(fixed_data, f, indent=2, ensure_ascii=False)
                print(f"✅ 正規化完了: {f_path}")
            else:
                print(f"ℹ️ 変更なし: {f_path}")
                
        except Exception as e:
            print(f"❌ エラー ({f_path}): {e}")

if __name__ == "__main__":
    fix_paths()
