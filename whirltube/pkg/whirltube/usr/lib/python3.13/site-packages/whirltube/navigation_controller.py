from __future__ import annotations


import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk

class NavigationController:
    def __init__(self, stack: Gtk.Stack, btn_back: Gtk.Button) -> None:
        self.stack = stack
        self.btn_back = btn_back
        self._nav_stack: list[str] = []  # back stack of stack view names

        self.btn_back.connect("clicked", self.go_back)
        self._update_back_button_visibility()

    def _update_back_button_visibility(self) -> None:
        self.btn_back.set_visible(bool(self._nav_stack))

    def show_view(self, name: str) -> None:
        cur = self.stack.get_visible_child_name() or "results"
        if cur != name:
            self._nav_stack.append(cur)
        self.stack.set_visible_child_name(name)
        self._update_back_button_visibility()

    def go_back(self, *_a) -> None:
        if self._nav_stack:
            prev = self._nav_stack.pop()
            self.stack.set_visible_child_name(prev)
        else:
            self.stack.set_visible_child_name("results")
        self._update_back_button_visibility()

    def clear_history(self) -> None:
        self._nav_stack.clear()
        self._update_back_button_visibility()
