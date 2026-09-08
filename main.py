import subprocess
import shutil
from findmicrosoftapp import find_app

apps={
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "vscode": r"C:\Users\Hi\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    "steam": r"C:\Program Files (x86)\Steam\steam.exe",
    "obsidian": r"C:\Users\Hi\AppData\Local\Programs\Obsidian\Obsidian.exe",
    "notion": r"C:\Users\Hi\AppData\Local\Programs\Notion\Notion.exe"
}

while True:
    command=input("You: ")
    command=command.lower().strip()

    if command=="hello":
        print("KM-Lone: Hello! I am KM-Lone. How can I assist you today?")
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