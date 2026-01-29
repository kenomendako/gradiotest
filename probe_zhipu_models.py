import requests
import json
import os
import sys

# Add current directory to path to allow importing config_manager
sys.path.append(os.getcwd())
import config_manager

def probe_models():
    # Load config to get API Key
    config_manager.load_config()
    api_key = config_manager.ZHIPU_API_KEY
    
    if not api_key:
        print("Error: ZHIPU_API_KEY not found in config.")
        return

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    chat_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    
    candidate_models = [
        "glm-4",
        "glm-4-flash",
        "glm-4-plus",
        "glm-4-air",
        "glm-4-long",
        "glm-4v",
        "glm-4.7",
        "glm-4.7-flash",
        "glm-zero-preview"
    ]
    
    print(f"--- Probing Zhipu AI Models ---")
    print(f"Using API Key: {api_key[:5]}...{api_key[-5:]}")
    
    results = {}
    
    for model in candidate_models:
        print(f"\nTesting model: {model}")
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Hello"}]
        }
        
        try:
            response = requests.post(chat_url, headers=headers, json=payload, timeout=10)
            
            status = response.status_code
            try:
                data = response.json()
            except:
                data = {"error": response.text}
                
            code = data.get("error", {}).get("code")
            msg = data.get("error", {}).get("message")
            
            print(f"  Status: {status}")
            print(f"  Code: {code}")
            print(f"  Message: {msg}")
            
            if status == 200:
                results[model] = "VALID (200 OK)"
            elif code == "1211":
                results[model] = "INVALID (1211 Model not found)"
            elif status == 429:
                results[model] = f"VALID but blocked ({status} {code}: {msg})"
            else:
                results[model] = f"UNKNOWN ({status} {code}: {msg})"
                
        except Exception as e:
            print(f"  Error: {e}")
            results[model] = f"ERROR ({e})"

    print("\n\n--- SUMMARY ---")
    for model, result in results.items():
        print(f"{model:<15}: {result}")

if __name__ == "__main__":
    probe_models()
