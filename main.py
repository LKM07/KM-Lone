import subprocess
import shutil
import os
from findmicrosoftapp import find_app
from material_search import (
    enable_debug_logging,
    extract_material_topic,
    format_material_report,
    search_materials,
)

apps={
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "vscode": r"C:\Users\Hi\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    "steam": r"C:\Program Files (x86)\Steam\steam.exe",
    "obsidian": r"C:\Users\Hi\AppData\Local\Programs\Obsidian\Obsidian.exe",
    "notion": r"C:\Users\Hi\AppData\Local\Programs\Notion\Notion.exe"
}

def main():
    if os.getenv("KM_LONE_DEBUG") == "1":
        enable_debug_logging()
        print("KM-Lone: Debug logging is enabled in km_lone_debug.log.")

    while True:
        raw_command=input("You: ").strip()
        command=raw_command.lower()
        material_topic = extract_material_topic(raw_command)

        if material_topic:
            report = search_materials(material_topic)
            print(format_material_report(report))
        elif command=="hello":
            print("KM-Lone: Hello! I am KM-Lone. How can I assist you today?")
        elif command=="help":
            print('KM-Lone: Try "open chrome" or "search materials about neural networks".')
        elif command=="exit":
            print("KM-Lone: Have a nice day!")
            break
        elif command.startswith("open"):
            app=command.replace("open", "", 1).strip()

            if app in apps:
                print(f"KM-Lone: Opening {app}...")
                subprocess.Popen(apps[app])
            else:
                program=shutil.which(app)
                if program:
                    print(f"KM-Lone: I found {app}. Opening...")
                    subprocess.Popen(program)
                else:
                    program=find_app(app)
                    if program:
                        print(f"KM-Lone: I found {app}. Opening...")
                        subprocess.Popen(program)
                    else:
                        print(f"KM-Lone: Sorry, I don't know how to open {app}.")
        else:
            print("KM-Lone: I'm sorry, I don't understand. Please try again.")


if __name__ == "__main__":
    main()
