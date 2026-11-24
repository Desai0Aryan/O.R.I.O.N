"""Mac (and general) polish that is optional: show on every Space, no Dock icon, a global hotkey."""
import sys


def mac_menubar_app():
    """macOS: live in the menu bar like a proper assistant instead of showing a Dock icon."""
    if sys.platform != "darwin":
        return False
    try:
        from AppKit import NSApp, NSApplicationActivationPolicyAccessory
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        return True
    except Exception:
        return False


def show_on_all_spaces(widget):
    """macOS: stay visible on every desktop (Space) and above full-screen apps."""
    if sys.platform != "darwin":
        return False
    try:
        import objc
        from AppKit import (NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorFullScreenAuxiliary,
                            NSWindowCollectionBehaviorStationary)
        view = objc.objc_object(c_void_p=int(widget.winId()))
        win = view.window()
        win.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary
                                   | NSWindowCollectionBehaviorStationary)
        win.setLevel_(25)                                   # NSStatusWindowLevel: above ordinary windows
        return True
    except Exception:
        return False


def make_holographic(widget):
    """macOS: no window shadow, no background, floats above everything and on every Space, so the
    hologram looks projected straight onto your desktop instead of sitting in a window."""
    if sys.platform != "darwin":
        return False
    try:
        import objc
        from AppKit import NSColor
        view = objc.objc_object(c_void_p=int(widget.winId()))
        win = view.window()
        win.setHasShadow_(False)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setIgnoresMouseEvents_(False)
        show_on_all_spaces(widget)
        return True
    except Exception:
        return False


def set_click_through(widget, ignore):
    """macOS: let the mouse pass through this window (True) or catch it (False). Returns True when applied."""
    if sys.platform != "darwin":
        return False
    try:
        import objc
        view = objc.objc_object(c_void_p=int(widget.winId()))
        view.window().setIgnoresMouseEvents_(bool(ignore))
        return True
    except Exception:
        return False


class Hotkey:
    """A global keyboard shortcut (needs the optional pynput; on a Mac, allow Accessibility for your terminal)."""

    def __init__(self, combo, callback):
        self.listener = None
        self.error = ""
        try:
            from pynput import keyboard
            self.listener = keyboard.GlobalHotKeys({combo: callback})
            self.listener.daemon = True
            self.listener.start()
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"

    def stop(self):
        try:
            if self.listener:
                self.listener.stop()
        except Exception:
            pass
