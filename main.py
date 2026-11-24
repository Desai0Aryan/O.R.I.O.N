"""Run Orion:  python main.py            (type to chat)
              python main.py --voice    (talk; say 'Orion, ...')"""
import argparse
import os
import re
import sys
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)   # always work from the project folder

import yaml
from dotenv import load_dotenv

from orion.agent import Agent

EXIT_WORDS = {"exit", "quit", "goodbye", "bye", "shut down"}


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", action="store_true", help="use microphone and speaker")
    args = ap.parse_args()

    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    name = cfg.get("assistant_name", "Orion")
    use_voice = args.voice or cfg.get("voice", {}).get("enabled", False)

    voice = None
    if use_voice:
        from orion.voice import Voice
        cfg["voice"]["name"] = name
        voice = Voice(cfg)
        speak = voice.say
    else:
        def speak(text):
            print(f"\n{name}: {text}")

    def confirm(question):
        return input(f"\n[{name} asks permission] {question} (y/n): ").strip().lower().startswith("y")

    agent = Agent(cfg, speak, confirm)
    print(f"{name} online using brain: {agent.brain.provider}. Say or type 'goodbye' to quit.")
    speak(f"Hello{', ' + cfg['user_name'] if cfg.get('user_name') else ''}. {name} is online.")

    wake = cfg.get("voice", {}).get("wake_word", "orion").lower()
    try:
        while True:
            try:
                if voice:
                    heard = voice.listen()
                    if not heard or wake not in heard.lower():
                        continue
                    text = re.sub(rf"\b{re.escape(wake)}\b[,.!?]*", "", heard, flags=re.I).strip() or "I'm here."
                    print(f"\nYou: {text}")
                else:
                    text = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not text:
                continue
            if text.lower().strip(" .!") in EXIT_WORDS:
                speak("Goodbye. I'll be here.")
                break
            try:
                agent.handle(text)
            except Exception as e:
                print(f"[error] {type(e).__name__}: {e}")
    finally:
        if cfg.get("learning", {}).get("reflect_on_exit", True):
            print("Saving what I learned...")
            agent.reflect()
    sys.exit(0)


if __name__ == "__main__":
    main()
