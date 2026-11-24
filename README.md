# Orion: Part 1 (Core) v2

Your personal AI assistant: swappable brain, personality with moods, voice in and out,
and memory that persists and grows. Tools (web, screen control, coding) come in later parts.

## Roadmap
| Part | What it adds | Status |
|------|--------------|--------|
| 1 | Brain, personality + mood, voice, persistent memory, learning, installer, autostart | this zip |
| 2 | Tools: weather, web search, open apps/sites, files, safe shell, "study" (learn from the internet) | next |
| 3 | Screen control (mouse/keyboard) with confirmations, vision | later |
| 4 | Coding: hand jobs to Claude Code (uses your Claude Pro login) | later |
| 5 | Background mode, tray icon, better wake word | later |
| 6 | "Jarvis" phase: phone / other-device companion app | later |

## Install ONCE
Install Python 3.10+ from python.org first (Windows: tick "Add Python to PATH").
Then unzip this folder somewhere permanent (for example your Documents folder) and:
- **Windows:** double-click `install.bat`
- **Mac/Linux:** open a terminal in the folder and run `bash install.sh`

That creates the environment and installs everything. You never repeat this.

## Choose a brain (edit `config.yaml`, change any time)
- **Local and free:** install Ollama (ollama.com), run `ollama pull llama3.1:8b` once.
  The model stays on your disk; Ollama starts with your computer. Needs about 8 GB RAM.
- **Claude API:** key from console.anthropic.com pasted into `.env` as `ANTHROPIC_API_KEY=`.
  A Claude Pro subscription does not include API access; the API is billed separately.
  (Pro is used in Part 4 through Claude Code.)
- **Free hosted API:** set `provider: openai_compatible`, choose a base URL and model
  (Groq, OpenRouter...), put the key in `.env` as `OPENAI_COMPAT_API_KEY=`.

Also set `user_name` and `home_city` in `config.yaml`.

## Every day
- **Windows:** double-click `run_orion.bat` (type chat). For voice: run `run_orion.bat --voice`.
- **Mac/Linux:** `./run_orion.sh` or `./run_orion.sh --voice`.

## Make Orion start by itself when you log in (voice mode)
- **Windows:** double-click `enable_autostart.bat`
- **Mac/Linux:** `bash enable_autostart.sh`
(Each script prints how to undo it.) Use a brain that is available at startup: Ollama, or an API key.

## What persists (nothing is lost when you shut down)
Everything lives in the `data/` folder inside the project: `orion_memory.db` holds facts about you,
lessons, notes, mood and the full conversation log. Your settings are in `config.yaml` and `.env`.
Back up or copy the `data/` folder to keep Orion's memory when you move computers.
To update Orion's code in future parts, unzip over the old folder and keep your `data/`,
`config.yaml` and `.env`.

## How Orion learns and grows
- **Facts:** things about you (people, projects, routines, tastes).
- **Lessons:** corrections and preferences about how to work with you. They are fed back into
  every conversation, so he adapts to you.
- **Reflection:** every few turns and when you say goodbye, Orion reviews the conversation
  and keeps what is worth remembering. Tune it under `learning:` in `config.yaml`.
- **Notes from the world:** a notes store for things learned from the internet and files.
  Part 2 adds web search and a "study" routine that fills it, and relevant notes are pulled in
  automatically when you talk about a topic.
- **Tidying:** when memory gets large, Orion merges duplicates so it stays sharp.
Be aware: this is learning through memory, not retraining the underlying model. The
model itself stays the same; Orion's knowledge of you and the world is what grows.

## Try it
- "Remember that I'm job hunting in marketing."
- "From now on keep answers to two sentences." (it should record a lesson)
- Say goodbye, restart, then ask "what do you know about me?"

## Troubleshooting
- Microphone errors: allow mic access for your terminal/Python. Linux: install `portaudio19-dev`.
- Robotic voice: use `tts: edge` (needs internet) and try voices like `en-US-AriaNeural`.
- Ollama "connection refused": open the Ollama app first.
- Replies look like raw JSON: the local model is too small; try a bigger one or the Claude API.
- Autostart does nothing: check `data/orion.log` (Mac) and that your brain is reachable at login.
