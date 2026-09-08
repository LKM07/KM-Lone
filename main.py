import subprocess
import os

while True:
    command=input("You: ")
    if command=="hello":
        print("KM-Lone: Hello! I am KM-Lone. How can I assist you today?")
    elif command=="exit":
        print("KM-Lone: Have a nice day!")
        break
    elif command=="open chrome":
        subprocess.Popen(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    else:
        print("KM-Lone: I'm sorry, I don't understand. Please try again.")