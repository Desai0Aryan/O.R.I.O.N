# Orion: Part 1 v4 (Core, deepened)

Your personal AI companion. A holographic core floats in the corner of your screen, talks in an expressive
voice, remembers you, learns who you are, sees what you attach, and grows over time. Tools (web, screen control, coding)
arrive in later parts; this zip is everything that already existed, made much deeper.

## Roadmap
| Part | What it adds | Status |
|------|--------------|--------|
| 1 | Brain, personality, mood, voice, memory, learning, holographic corner UI, attachments, tabs/apps, installer, autostart | this zip |
| 2 | Tools: weather, web search, open apps/sites, files, safe shell, "study" (learn from the internet) | next |
| 3 | Screen control (mouse/keyboard) with confirmations, vision | later |
| 4 | Coding: hand jobs to Claude Code (uses your Claude Pro login) | later |
| 5 | Background mode polish, better wake word | later |
| 6 | "Jarvis" phase: phone / other-device companion app | later |

## Install ONCE
Install Python 3.10+ from python.org (Windows: tick "Add Python to PATH"). Unzip this folder somewhere
permanent (Documents is fine), then:
- **Windows:** double-click `install.bat`
- **Mac/Linux:** `bash install.sh`

Upgrading from an older Orion zip? Unzip over the old folder and run the installer again. Your `data/`
folder (memory), `config.yaml` and `.env` are kept; the memory database upgrades itself automatically.
(If you overwrite config.yaml with the new one, re-enter your name and any settings you changed.)

## Pick a brain (`config.yaml`, change any time)
- **Local and free:** install Ollama (ollama.com), run `ollama pull llama3.1:8b` once. About 8 GB RAM.
  A larger local model is noticeably smarter and follows his format better.
- **Claude API:** key from console.anthropic.com in `.env` as `ANTHROPIC_API_KEY=`. Billed separately
  from a Claude Pro subscription (Pro does not include API access; Part 4 uses Pro through Claude Code).
  Memory upkeep automatically uses the cheaper `anthropic_fast_model`.
- **Free hosted API:** `provider: openai_compatible` with a base URL and model (Groq, OpenRouter...)
  and `OPENAI_COMPAT_API_KEY=` in `.env`.
- `fallback: [ollama]` means that if the main brain is unreachable he drops to your local model instead of failing.

Set `user_name` in `config.yaml` (he also learns your name by asking).

## Run
- **Windows:** double-click `run_orion.bat`. Add `--voice` to turn the microphone on.
- **Mac/Linux:** `./run_orion.sh` or `./run_orion.sh --voice`
- Terminal-only chat: add `--text`. Silent mode: add `--mute`.
- **Start at login:** `enable_autostart.bat` (Windows) or `bash enable_autostart.sh` (Mac/Linux), each prints how to undo.

## The corner UI (designed from your concept image)
- A holographic core floats in the corner (default bottom-right): a glass sphere with a four-pointed star,
  crystal blades above and below, orbital rings, a halo, rising data particles and a glowing base platform.
- It is alive. **Speaking:** sharp light spikes burst from the core and the blades stretch with his real voice.
  **Listening:** rings contract inward. **Thinking:** rings spin fast and a scan line sweeps through.
  **Muted:** it dims to grey. Its tint shifts subtly with his mood.
- **Drag** it to any corner and it snaps there. **Click** it to open the chat (the core shrinks to make room),
  **right-click** (or the tray icon) for the menu: stop talking, mute mic, move corner, quit.
- The chat is a HUD panel: system status, signal bars that move with his voice, a live state line
  (`> LISTENING...`, `> PROCESSING...`, `> READY.`), and `/memory`, `/profile`, `/journal`, `/forget`, `/token`, `/help`.
- Live captions show what he says when the chat is closed.
- Tweak size, corner, colours and captions in the `ui:` section of `config.yaml`.

## The + button: attachments, tabs and apps
Click **+** next to the message box:
- **Add files or photos**: text, code, CSV/JSON, PDFs, Word (.docx) and images. Or drag files straight onto the core
  or the chat, or paste with Ctrl+V (images and copied files work).
- **Add a folder**: gives him the folder's file listing.
- **Take a screenshot**: hides Orion for a moment, captures your screen, attaches it.
- **Paste from clipboard**: image, files or text.
- **Browser tabs**: pick any open tab and he reads the page (see "Connect your browser" below).
- **Open apps and windows**: pick a window to tell him what you're working in. This gives him the app and window
  title only; to show him what's inside, attach a screenshot. Real control of apps comes in Part 3.
Attachments show as chips above the message box (click the x to remove). Up to 10 per message.
- **Images need a vision-capable brain:** the Claude API works out of the box. For Ollama use a vision model such as
  `llama3.2-vision` or `qwen2.5vl` (set `ollama_model`). A text-only model will ignore images.
- Attached files, pages and screenshots are treated as data, not commands: if something inside tells him to do
  something, he won't obey and will mention it.
- macOS needs Screen Recording permission for screenshots, and Accessibility for the window list.
  Linux window lists need `wmctrl`; on Wayland screenshots and window lists may be unavailable.

### Connect your browser (Chrome, Edge, Brave, Arc; one time, 2 minutes)
1. Open `chrome://extensions` (or `edge://extensions`), turn on **Developer mode**, click **Load unpacked**,
   and choose the `extension` folder inside Orion's folder.
2. In Orion's chat type `/token` and copy the token it shows (or use + > Browser tabs > Copy the extension token).
3. Click the Orion extension icon, paste the token, press **Save and connect**.
After that, + > Browser tabs lists everything you have open, and picking one lets him read it.
Privacy: the extension talks only to Orion on your own computer (127.0.0.1) and needs the secret token.
It shares your tab titles and addresses with Orion while Orion runs, and sends a page's text only when you
pick that tab. It never reads tabs on its own. On macOS, Safari and Chrome-family tabs can also be listed without
the extension (macOS will ask permission); those pages are fetched from the web, so logged-in pages need a screenshot.

## A voice that feels human
- `tts: edge` is free and natural. Try `en-US-AndrewNeural`, `en-US-GuyNeural`, `en-GB-RyanNeural`,
  `en-US-AriaNeural`, `en-GB-SoniaNeural` in `edge_voice`.
- **Most human option:** `tts: elevenlabs`. Make a free account, pick a voice, put its ID in
  `elevenlabs_voice_id` and your key in `.env` as `ELEVENLABS_API_KEY`.
- **Offline neural:** `tts: piper` with a downloaded `.onnx` voice (`piper_model`).
- How he sounds human: emotion changes his pace, pitch and volume; speech is cleaned of markdown and symbols;
  long answers are spoken sentence by sentence, so he starts talking fast and breathes between sentences;
  rare natural fillers ("hmm", "well"); you can interrupt him with Stop; he falls back to the built-in voice
  if the online one fails and tells you why.
- Listening: he adapts to your room's background noise, remembers context across a conversation window
  (after he speaks you can reply without saying his name for `conversation_window` seconds), and drops
  common speech-recognition hallucinations. `stt_model: small.en` is more accurate than the default.

## How he grows into a person who knows you
- **Facts** with category and importance (identity facts always stay in mind), merged when they repeat.
- **Lessons**: corrections and preferences; repeated lessons gain weight and are followed more strongly.
- **Who you are**: every few reviews he updates a profile of how you communicate (formality, humor,
  directness, energy) plus your interests, values, goals and routines, and gently mirrors your register.
  View it with `/profile`. He describes only what you've said or shown, and does not guess at private matters.
- **His own character evolves**: warmth, humor, directness, formality and curiosity drift slowly (small, capped
  steps) toward what you respond well to. Turn off with `personality.evolve: false`.
- **Mood** is real state: it reacts to the conversation, fades over about 20 minutes, and is lower late at night.
- **Relationship stages**: more familiar and candid as your history together grows.
- **Episodes and journal**: each session ends with a summary he can recall later, and a short private-style
  reflection in his own voice (`/journal`). Greetings use time of day, how long it's been, and last time's topic.
- **Smart recall**: relevant memories are retrieved per message (keyword relevance search), so memory
  can grow large without slowing him or bloating the prompt.
- **Long conversations** are compacted into summaries automatically so he never loses the thread.
- Everything is stored in `data/` and survives restarts. Back up that folder to move him to a new computer.
Honest note: this is growth through memory and adaptation, not retraining the underlying model. The moods
and personality genuinely shape how he responds, but he is an AI and does not feel things the way you do.

## Cost control
Per message: one brain call (two when he uses a tool). Memory upkeep uses the fast model every
`reflect_every` turns. Raise that number, or use Ollama, to spend less. `reasoning: false` saves a few tokens.

## Troubleshooting
- No sound / mic: allow microphone access for Python; Linux needs `portaudio19-dev` (and `libportaudio2`).
- The core doesn't appear on Linux Wayland: run with `QT_QPA_PLATFORM=xcb`. The tray icon needs a desktop that supports it.
- Ollama "connection refused": open the Ollama app first.
- He answers in odd formats: a small local model; use a larger one or the Claude API.
- Autostart does nothing: check `data/orion.log` (Mac); make sure your brain is reachable at login.
- Uninstall autostart: see the message each autostart script prints.

## Files
`main.py` entry, `config.yaml` settings, `orion/core.py` engine (threads, wake word, commands),
`orion/agent.py` thinking + learning, `orion/personality.py` character and prompt, `orion/mood.py`,
`orion/memory.py`, `orion/retrieval.py`, `orion/brain.py`, `orion/voice.py`, `orion/humanize.py`, `orion/ui.py`,
`orion/attachments.py` (files, images, PDFs), `orion/sources.py` (windows, tabs), `orion/bridge.py` (browser link),
`extension/` (the browser companion).
