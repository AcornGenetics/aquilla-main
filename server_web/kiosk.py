#!/usr/bin/env python3
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")

from gi.repository import Gtk, WebKit2, Gdk

# Change this if you serve via lighttpd instead:
#URL = "file:///home/pi/app/dist/index.html"
#URL="http://127.0.0.1:8090"
URL = "http://localhost:8090"  # Aquilla web UI

class KioskWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Kiosk")
        self.set_decorated(False)
        self.fullscreen()

        self.connect("destroy", Gtk.main_quit)
        self.connect("key-press-event", self.on_key_press)

        self.webview = WebKit2.WebView()
        settings = self.webview.get_settings()
        settings.set_property("enable-javascript", True)
        settings.set_property("enable-accelerated-2d-canvas", True)
        settings.set_property("enable-webaudio", True)

        self.webview.load_uri(URL)
        self.add(self.webview)
        self.show_all()

    def on_key_press(self, widget, event):
        # Allow quitting with Ctrl+Alt+Q (useful during testing)
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(event.state & Gdk.ModifierType.MOD1_MASK)
        if ctrl and alt and event.keyval == Gdk.keyval_from_name("q"):
            Gtk.main_quit()

def main():
    win = KioskWindow()
    Gtk.main()

if __name__ == "__main__":
    main()
