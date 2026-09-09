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
from material_summary import (
    SummaryError,
    extract_summary_target,
    format_summary,
    resolve_material,
    summarise_material,
    terminal_text,
)
from voice_input import VoiceError, VoiceInput, list_microphones, setup_voice

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

    last_report = None
    summary_cache = {}
    voice = VoiceInput()
    print('KM-Lone: Type a command, or enter "voice" to speak. Use "help" for examples.')

    while True:
        try:
            raw_command = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nKM-Lone: Have a nice day!")
            break
        command=raw_command.lower()
        if command in {"voice", "voice en", "voice zh", "voice auto", "voice devices", "voice setup"}:
            try:
                if command == "voice devices":
                    print(terminal_text(list_microphones()))
                    continue
                if command == "voice setup":
                    setup_voice()
                    continue
                language = command.split()[1] if command in {"voice en", "voice zh"} else None
                raw_command = voice.listen(language)
                print(f"You (voice): {terminal_text(raw_command)}")
                command = raw_command.lower()
            except VoiceError as error:
                print(f"KM-Lone: {error}")
                continue
            except KeyboardInterrupt:
                print("\nKM-Lone: Voice cancelled. You can type or try again.")
                continue
        summary_target = extract_summary_target(raw_command)
        if summary_target is not None:
            try:
                material = resolve_material(summary_target, last_report)
                if material.url not in summary_cache:
                    print("KM-Lone: Reading the selected material...")
                    summary_cache[material.url] = summarise_material(material)
                print(format_summary(summary_cache[material.url]))
            except SummaryError as error:
                print(f"KM-Lone: {error}")
            except KeyboardInterrupt:
                print("\nKM-Lone: Summary cancelled. You can enter another command.")
            continue

        material_topic = extract_material_topic(raw_command)

        if material_topic:
            # A new search replaces the numbered list, including on zero results.
            last_report = None
            summary_cache.clear()
            report = search_materials(material_topic)
            last_report = report
            print(terminal_text(format_material_report(report)))
        elif command=="hello":
            print("KM-Lone: Hello! I am KM-Lone. How can I assist you today?")
        elif command=="help":
            print('KM-Lone: Try "open chrome", "search materials about neural networks", '
                  '"summarise 3", or "summarise <displayed URL>". '
                  'Use "voice" (auto), "voice en" or "voice zh" to speak; '
                  '"voice devices" lists microphones, "voice setup" downloads the model. Use "exit" to leave.')
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
