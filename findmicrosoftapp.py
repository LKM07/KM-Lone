import os

def find_app(app_name):
    print(f"Searching for {app_name}...")

    app_files = {
        "word": "WINWORD.EXE",
        "excel": "EXCEL.EXE",
        "powerpoint": "POWERPNT.EXE",
        "onenote": "ONENOTE.EXE",
        "outlook": "OUTLOOK.EXE"
    }

    if app_name.lower() not in app_files:
        print(f"Could not find {app_name}.")
        return None

    target_file = app_files[app_name.lower()]

    folder = r"C:\Program Files\Microsoft Office"

    for root, dirs, files in os.walk(folder):
        for file in files:
            if file.lower() == target_file.lower():
                path = os.path.join(root, file)

                print(f"Found: {path}")

                return path

    print(f"Could not find {app_name}.")
    return None