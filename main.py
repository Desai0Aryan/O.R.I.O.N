"""Run Orion.
   python main.py            floating orb in the corner of your screen (default)
   python main.py --voice    same, with the microphone on (say 'Orion, ...')
   python main.py --text     plain terminal chat
   python main.py --mute     no spoken voice"""
import argparse
import os
import sys
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)       # always work from the project folder

import yaml
from dotenv import load_dotenv

EXIT_WORDS = {"exit", "quit", "goodbye", "bye", "shut down"}


def run_terminal(cfg):
    from orion.core import Core
    name = cfg.get("assistant_name", "Orion")

    def emit(kind, **kw):
        if kind == "assistant":
            text = kw.get("display") or kw.get("speech")
            if text:
                print(f"\n{name}: {text}")
        elif kind == "system":
            print(f"[{kw.get('level', 'info')}] {kw.get('text', '')}")

    def confirm(q):
        return input(f"\n[{name} asks permission] {q} (y/n): ").strip().lower().startswith("y")

    core = Core(cfg, emit, confirm=confirm)
    print(f"{name} online using brain: {core.agent.brain.provider}. Type 'goodbye' to quit, /help for commands.")
    core.start()
    try:
        while True:
            text = input("\nYou: ").strip()
            if not text:
                continue
            if text.lower().strip(" .!") in EXIT_WORDS:
                break
            core.stop_speaking()
            core.process(text, "typed")
    except (EOFError, KeyboardInterrupt):
        pass
    print("Saving what I learned...")
    core.shutdown()
    return 0


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", action="store_true", help="turn the microphone on")
    ap.add_argument("--text", action="store_true", help="terminal chat instead of the floating UI")
    ap.add_argument("--mute", action="store_true", help="do not speak out loud")
    args = ap.parse_args()

    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg.setdefault("voice", {})
    if args.voice:
        cfg["voice"]["listen"] = True
    if args.mute:
        cfg["voice"]["speak"] = False

    if not args.text and cfg.get("ui", {}).get("enabled", True):
        try:
            from orion.ui import run_ui
        except ImportError as e:
            print(f"UI unavailable ({e}). Run install again or use --text. Falling back to terminal.")
        else:
            return run_ui(cfg)
    return run_terminal(cfg)


if __name__ == "__main__":
    sys.exit(main())
