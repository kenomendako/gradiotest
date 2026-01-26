import os
import re
import urllib.parse
import argparse

# Configuration
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # nexus_ark/
DOCS_DIR = os.path.join(PROJECT_ROOT, "docs")

# Windows absolute path prefixes to detect
# Case insensitive check will be applied
PREFIXES = [
    r"file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/",
    r"file:///C:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/",
    r"file:///c:/users/baken/onedrive/デスクトップ/gradio_github/gradiotest/",
    # Encoded versions
    r"file:///c:/Users/baken/OneDrive/%E3%83%87%E3%82%B9%E3%82%AF%E3%83%88%E3%83%83%E3%83%97/gradio_github/gradiotest/",
    r"file:///C:/Users/baken/OneDrive/%E3%83%87%E3%82%B9%E3%82%AF%E3%83%88%E3%83%83%E3%83%97/gradio_github/gradiotest/",
]

# Regex to find links: [text](url)
LINK_PATTERN = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')

def normalize_path_sep(path):
    return path.replace("\\", "/")

def get_relative_path(target_abs_path, current_file_path):
    """
    Calculates relative path from current_file_path to target_abs_path.
    """
    current_dir = os.path.dirname(current_file_path)
    rel_path = os.path.relpath(target_abs_path, current_dir)
    return normalize_path_sep(rel_path)

def process_file(file_path, dry_run=False):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    new_content = content
    modified = False
    
    def replacement(match):
        nonlocal modified
        text = match.group(1)
        url = match.group(2)
        
        # Check if URL matches any prefix
        matched_prefix = None
        for prefix in PREFIXES:
            # Simple case-insensitive check for the start
            # We unquote both just to compare cleanly if mixed encoded/decoded
            decoded_url = urllib.parse.unquote(url)
            decoded_prefix = urllib.parse.unquote(prefix)
            
            if decoded_url.lower().startswith(decoded_prefix.lower()):
                matched_prefix = prefix # Store original prefix logic if needed, but we use decoded mostly
                
                # Extract the part after prefix: local repostiory path
                # e.g. docs/reports/foo.md
                repo_rel_path = decoded_url[len(decoded_prefix):]
                
                # Construct absolute path in current environment (Linux) to calculate relative path safely
                # PROJECT_ROOT is /home/baken/nexus_ark
                # repo_rel_path might use / or \
                repo_rel_path = repo_rel_path.replace("\\", "/")
                
                # Verify if it looks like a file in our repo (optional, but good for safety)
                # But even if file doesn't exist locally (deleted?), relative path is still valid structurally.
                target_abs_path = os.path.join(PROJECT_ROOT, repo_rel_path)
                
                # Calculate new relative path
                new_url = get_relative_path(target_abs_path, file_path)
                
                modified = True
                print(f"[FIX] {file_path}:\n  Old: {url}\n  New: {new_url}")
                return f"[{text}]({new_url})"
        
        return match.group(0)

    new_content = LINK_PATTERN.sub(replacement, content)

    if modified and not dry_run:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

def main():
    parser = argparse.ArgumentParser(description="Fix Windows absolute paths in documentation.")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without modifying files.")
    args = parser.parse_args()

    print(f"Project Root: {PROJECT_ROOT}")
    print("Scanning docs/ directory and root py files...")

    # 1. Scan docs/ recursively
    for root, dirs, files in os.walk(DOCS_DIR):
        for file in files:
            if file.endswith(".md"):
                process_file(os.path.join(root, file), args.dry_run)

    # 2. Scan specific root files if needed (e.g. CHANGELOG.md is in root, not docs/)
    root_files = ["CHANGELOG.md", "nexus_ark.py", "ui_handlers.py"]
    for rf in root_files:
        p = os.path.join(PROJECT_ROOT, rf)
        if os.path.exists(p):
            process_file(p, args.dry_run)

    print("Done.")

if __name__ == "__main__":
    main()
