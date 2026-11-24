# Orion: Part 1 v7 (a living hologram, star-map memory, timers, sounds)

Your personal AI companion. A holographic core floats in the corner of your screen, talks in an expressive
voice, remembers you, learns who you are, sees what you attach, and grows over time. Tools (web, screen control, coding)
arrive in later parts; this zip is everything that already existed, made much deeper.

## Roadmap
| Part | What it adds | Status |
|------|--------------|--------|
| 1 | Brain, personality, mood, voice, memory, learning, holographic corner UI, attachments, tabs/apps, installer, autostart | this zip |
| 2 | Internet tools (web search, pages, weather, news, Wikipedia, papers, study) arrived early in v6. Still to come: open apps/sites, files, safe shell | partly done |
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

## The corner UI (a real 3D particle hologram)
- A holographic core floats in the corner (default bottom-right). It is a live 3D point cloud, not a flat picture:
  thousands of glowing particles form a rotating sphere with a bright core, a wireframe globe, a data mesh with
  travelling packets, orbital rings with comet heads, a dial ring, rotating data cubes, drifting dust and a projector base.
- It is alive. **Speaking:** light spikes burst outward, driven by the bass, mid and high frequencies of his real voice
  (bass pushes the shell, mids add turbulence, highs sparkle). **Listening:** rings contract inward and it pulses when it hears you.
  **Thinking:** the sphere spins faster and a scan sweeps through. **Muted:** it dims to grey. The tint shifts with his mood.
- Performance: it is drawn on the CPU with numpy (no GPU needed). On a slow computer it automatically lowers its own
  quality. In `config.yaml`, `ui.quality` (1.0 fastest, up to 2.0 sharpest) and `ui.orb_size` control it.
- **Drag** it to any corner and it snaps there. **Click** it to open the chat (the core shrinks to make room),
  **right-click** (or the tray icon) for the menu: stop talking, mute mic, move corner, quit.
- The chat is a HUD panel: system status, signal bars that move with his voice, a live state line
  (`> LISTENING...`, `> PROCESSING...`, `> READY.`), and `/memory`, `/profile`, `/journal`, `/forget`, `/token`, `/help`.
- Live captions show what he says when the chat is closed.

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

## New in v7: the show
**The hologram is now a presence, not a picture.**
- **He looks at you.** His whole body turns to follow your cursor, and when nobody is around he glances about on his own.
  He dims and slows at night and drifts into a sleepy glow if you leave him alone for ten minutes.
- **Boot sequence.** At launch particles stream in from the dark and snap into place, a console types out
  `> ORION CORE ONLINE / MEMORY 63 FACTS / BRAIN ... / ALL SYSTEMS NOMINAL`, and a rising chime plays.
- **A voice ring.** A circular audio visualiser around the core draws his voice (and yours) as bars: bass at the bottom,
  mids at the sides, highs on top. Shockwaves roll out when he hears you or when a reminder fires.
- **Lightning while he thinks.** Jagged bolts crackle across the sphere.
- **The constellation Orion** hangs behind him, drawn star by star. Its three belt stars chase each other like a loading light while he thinks.
- **Six themes:** `arc` (blue), `ember` (orange), `aurora` (green), `nebula` (violet), `crimson` (red), `ghost` (silver).
  Type `/theme ember` or use the menu. The chat panel's colours follow, and he remembers your choice.

**The panel has three screens** (tabs under the header):
- **CHAT:** now shows what he is doing as he does it (`◈ Checking the weather: Malibu`), and a live weather card.
  Type `/` for a command menu.
- **MIND:** his memory as a night sky. Every fact and note is a star (colour = kind of memory, size = importance),
  linked memories form constellations, and a new memory flares up when it is born. Hover a star to read it.
- **STATUS:** clock, CPU / memory / battery gauges, his counters (facts, lessons, notes, days together), which brain is in use,
  and live countdown rings for your timers and reminders.

**New abilities**
- **Timers and reminders:** "set a timer for 10 minutes for the pasta", "remind me at 5:30 to call Maya", "remind me tomorrow at 9 to send
  the invoice". They survive restarts, and one that came due while he was off is delivered when he wakes. He speaks them,
  plays a chime and sends a shockwave. `/timer 10m tea`, `/remind 5pm call mom`.
- **Briefing:** `/brief` or "catch me up": time, weather at home, headlines, reminders, in a few warm sentences.
  Set `home_city` in `config.yaml` for the weather.
- **Sound design:** every sound is synthesised, no files: boot sweep, listening blip, thinking tick, reminder chime, error tone.
  Quiet by default. `ui.sounds: false` or `ui.sound_volume`.

**Mac polish** (everything is optional and fails quietly on other systems)
- Lives in the menu bar with no Dock icon, and stays visible on every Space and above full-screen apps
  (installed automatically through `pyobjc`).
- **Global hotkey** Ctrl+Option+O opens him from anywhere (`ui.hotkey`; needs Accessibility permission for the app that runs
  Orion: System Settings > Privacy & Security > Accessibility; blank the setting to switch it off).
- The microphone and screenshot permissions are asked by macOS the first time they are used.

## Earlier: v6
**Faster.** He now starts talking after the first sentence of his answer, while the rest is still being written,
and the next sentence is already being voiced while the current one plays, so there are no gaps. When he needs a
tool he says a short line ("Let me check.") first. Tools run side by side. Memory tidying no longer blocks the next turn.

**Hears better.** The microphone stays open all session so no word is missed. It filters low rumble, adapts to your
room's noise, boosts quiet talkers, ignores clicks and coughs, never hears his own voice, and decides you have finished
after 0.6 s of quiet (`voice.end_silence`). The speech model is now `small.en` (loaded at startup), and he gives it the
names from your life so it spells them right. For the best accuracy use `medium.en`; for the fastest, `base.en`.
If a microphone is wrong, set `voice.input_device`.

**His name.** He still shows "Orion" but says it as **Oh-ee-on** (`voice.say_name_as`; try "Oh-ree-on" or "Or-ee-on" if it
sounds off). He also catches mis-hearings of his name ("O E on", "Oh ee on", "Oreon"), so waking him is forgiving.

**Understands you.** He reasons in a fixed order: what kind of message it is, what you mean (using the conversation to resolve
"it" and "that"), whether to answer or look it up, then checks tool results before answering. Voice input is treated as
possibly mis-heard. When you correct him ("no, I meant...") he works out what he got wrong and learns the lesson.

**The internet and public databases.** Tools: `web_search` (DuckDuckGo; add `TAVILY_API_KEY` or `BRAVE_API_KEY` to `.env`
for better results), `read_page` (any public page or JSON API), `wikipedia`, `weather` (Open-Meteo, no key), `news`,
`arxiv` (papers), `define`, `exchange` (currencies), `calculate`. Pages are read as data, never as orders, and addresses on
your own network or computer are blocked. Set `home_city` and `tools.units` in `config.yaml`.

**Grows his own knowledge.** `study` researches a topic across several sources and saves sourced notes he recalls later.
When you are away he studies things from your interests and goals on his own (`learning.curiosity`, `study_every_hours`,
`study_per_day`; set `study_per_day: 0` to stop it, each study costs a few small model calls).

Honest limits: speed on a local model depends on your computer; the pronunciation could not be heard by me, only set;
search quality without a key is basic; he does not browse logged-in sites until Part 3.

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
`orion/memory.py`, `orion/retrieval.py`, `orion/brain.py`, `orion/voice.py`, `orion/humanize.py`, `orion/wake.py` (name matching), `orion/tools/` (internet, study, calculator), `orion/ui.py`,
`orion/attachments.py` (files, images, PDFs), `orion/sources.py` (windows, tabs), `orion/bridge.py` (browser link),
`extension/` (the browser companion).

## What's new in v8: a hologram on your desktop, and a chat app of its own

- **No container.** Orion is now a bare hologram floating over your wallpaper and windows (no frame, no box, no window
  shadow). On a Mac, clicks pass straight through the empty space around him and only the glowing shape catches the mouse.
  He shows on every Space and above full-screen apps. Drag him anywhere; he remembers where you left him.
  Ctrl/Cmd + scroll over him to resize, or use the right-click menu.
- **Projector look.** Faint scanlines with a slow bright sweep, colour fringing and the odd glitch flicker, which also
  fires when he starts listening or thinking. Turn off with `ui.holo_fx: 0` or the right-click menu.
- **Words as light.** Captions are glowing text beside him (no bubble), typed out as he speaks, then fading.
- **Timer rings.** A running timer wraps around him as a ring that slowly empties, with the time written under him.
- **The chat is its own app window.** Click him, press the hotkey (Ctrl+Alt+O), click his Dock icon or the menu-bar icon.
  Drag it by the header, resize from the bottom-right corner, `Esc` or `Cmd+W` hides it. Size and place are remembered.
  Set `ui.chat_on_top: true` to keep it above other apps, `ui.dock_icon: false` for menu-bar only.
- **Try it without a brain:** `python main.py --demo` plays a short scripted tour (speech, listening, thinking, themes, timer).
