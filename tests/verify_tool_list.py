
import os
import sys

# Add the project root to sys.path
sys.path.append(os.getcwd())

from agent.graph import all_tools

def verify_tools_list():
    tools_list_str = "\n".join([f"- `{tool.name}`: {tool.description[:50]}..." for tool in all_tools])
    print("--- Available Tools List ---")
    print(tools_list_str)
    
    # Check if our new tools are present
    new_tools = ["list_project_files", "read_project_file"]
    for nt in new_tools:
        if nt in tools_list_str:
            print(f"✅ Tool '{nt}' is in the list.")
        else:
            print(f"❌ Tool '{nt}' is MISSING from the list.")

if __name__ == "__main__":
    verify_tools_list()
