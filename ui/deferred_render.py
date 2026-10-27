"""Coalesce Tk layout callbacks without entering a nested draw."""
import tkinter as tk


class DeferredRender:
    def __init__(self, owner):
        self.owner = owner
        self.jobs = {}
        self.running = set()
        self.sizes = {}
        self.closed = False

    def request(self, key, callback):
        if self.closed or key in self.jobs:
            return

        def run():
            self.jobs.pop(key, None)
            if self.closed:
                return
            # CTk may process idle events while configuring widgets.
            if key in self.running:
                self.request(key, callback)
                return
            self.running.add(key)
            try:
                callback()
            finally:
                self.running.discard(key)

        self.jobs[key] = self.owner.after(50, run)

    def resize(self, key, size, callback):
        if self.sizes.get(key) == size:
            return
        self.sizes[key] = size
        self.request(key, callback)

    def close(self):
        self.closed = True
        for job in self.jobs.values():
            try:
                self.owner.after_cancel(job)
            except tk.TclError:
                pass
        self.jobs.clear()
