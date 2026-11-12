"""Small window for Forza Horizon 1 .xds textures and .xdc profile thumbnails.

Open an .xds or .xdc, see it as a picture, save it as PNG. You can also load an
edited PNG and save it back as an .xds or .xdc (same width and height as the
original), or just convert between .xdc and .xds.

Needs: python 3, numpy, pillow (tkinter comes with Python).
Run:  python xds_gui.py [file.xds|file.xdc]
"""
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageTk

import xds_tool as T


def checkerboard(w, h, size=12):
    y, x = np.mgrid[0:h, 0:w]
    c = (((x // size) + (y // size)) % 2) * 40 + 190
    return np.dstack([c, c, c]).astype(np.uint8)


class App:
    def __init__(self, root, path=None):
        self.root = root
        root.title("Forza XDS texture viewer")
        root.geometry("900x720")
        root.minsize(520, 420)
        self.rgba = None          # decoded image, numpy (H, W, 4)
        self.template = None      # original .xds bytes (header is reused when saving)
        self.src_path = None
        self.photo = None
        self.ignore_alpha = tk.BooleanVar(value=False)

        bar = ttk.Frame(root, padding=6)
        bar.pack(fill="x")
        ttk.Button(bar, text="Open .xds…", command=self.open_xds).pack(side="left")
        self.save_png_btn = ttk.Button(bar, text="Save as PNG…", command=self.save_png, state="disabled")
        self.save_png_btn.pack(side="left", padx=(6, 0))
        self.load_png_btn = ttk.Button(bar, text="Load edited PNG…", command=self.load_png, state="disabled")
        self.load_png_btn.pack(side="left", padx=(18, 0))
        self.save_xds_btn = ttk.Button(bar, text="Save as .xds…", command=self.save_xds, state="disabled")
        self.save_xds_btn.pack(side="left", padx=(6, 0))
        self.save_xdc_btn = ttk.Button(bar, text="Save as .xdc…", command=self.save_xdc, state="disabled")
        self.save_xdc_btn.pack(side="left", padx=(6, 0))
        ttk.Checkbutton(bar, text="Ignore alpha", variable=self.ignore_alpha,
                        command=self.redraw).pack(side="right")

        self.canvas = tk.Canvas(root, bg="#2b2b2b", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())

        self.status = tk.StringVar(value="Open an .xds file to start.")
        ttk.Label(root, textvariable=self.status, padding=6, anchor="w").pack(fill="x")

        if path:
            root.after(100, lambda: self.load_xds(path))

    # ---- actions ----------------------------------------------------------
    def open_xds(self):
        p = filedialog.askopenfilename(title="Open .xds or .xdc",
                                       filetypes=[("Xbox 360 textures", "*.xds *.xdc"), ("All files", "*.*")])
        if p:
            self.load_xds(p)

    def load_xds(self, path):
        try:
            self.status.set("Decoding…")
            self.root.update_idletasks()
            data = open(path, "rb").read()
            rgba, hd = T.decode(data)
        except Exception as e:  # unsupported format, bad file, ...
            messagebox.showerror("Cannot open", "%s\n\n%s" % (os.path.basename(path), e))
            self.status.set("Open an .xds file to start.")
            return
        self.rgba, self.src_path = rgba, path
        self.template = T.unpack_xdc(data) if T.is_xdc(data) else data   # always the .xds bytes
        self.src_is_xdc = T.is_xdc(data)
        for b in (self.save_png_btn, self.load_png_btn):
            b.config(state="normal")
        self.save_xds_btn.config(state="normal")
        self.save_xdc_btn.config(state="normal")
        self.root.title("Forza XDS texture viewer - " + os.path.basename(path))
        kind = T.FORMATS.get(hd["format"], ("?",))[0]
        self.status.set("%s   %d x %d   format 0x%02X (%s)   %s" % (
            os.path.basename(path), rgba.shape[1], rgba.shape[0], hd["format"], kind,
            "tiled" if hd["tiled"] else "linear") + ("   (compressed .xdc)" if self.src_is_xdc else "")
            + ("   WARNING: the pixel data in this file is noise (the file itself holds garbage, not a picture)" if T.looks_like_noise(rgba) else ""))
        self.redraw()

    def save_png(self):
        if self.rgba is None:
            return
        base = os.path.splitext(os.path.basename(self.src_path))[0] + ".png"
        p = filedialog.asksaveasfilename(title="Save as PNG", defaultextension=".png",
                                         initialfile=base, filetypes=[("PNG image", "*.png")])
        if p:
            T.write_png(p, self.rgba)
            self.status.set("Saved " + p)

    def load_png(self):
        """Replace the picture with an edited PNG (must be the same size)."""
        if self.template is None:
            return
        p = filedialog.askopenfilename(title="Load edited PNG", filetypes=[("PNG image", "*.png")])
        if not p:
            return
        img = np.asarray(Image.open(p).convert("RGBA"))
        if img.shape[:2] != self.rgba.shape[:2]:
            messagebox.showerror("Wrong size", "The PNG is %d x %d but the texture is %d x %d.\n"
                                 "Resize it to match exactly." % (img.shape[1], img.shape[0],
                                                                  self.rgba.shape[1], self.rgba.shape[0]))
            return
        self.rgba = img
        self.status.set("Loaded " + os.path.basename(p) + " - now use Save as .xds")
        self.redraw()

    def _encoded_xds(self):
        """Current picture as .xds bytes (None if the format cannot be saved)."""
        hd = T.parse_header(self.template)
        kind = T.FORMATS.get(hd["format"], ("",))[0]
        if kind not in ("8888", "DXT5"):
            messagebox.showerror("Not supported", "Saving this format (%s) is not supported yet." % kind)
            return None
        self.status.set("Encoding…")
        self.root.update_idletasks()
        enc = T.encode_dxt5 if kind == "DXT5" else T.encode_8888
        return enc(self.rgba, self.template)

    def _save_bytes(self, ext, make):
        if self.rgba is None:
            return
        base = os.path.splitext(os.path.basename(self.src_path))[0] + ("_new" if ext == ".xds" and not self.src_is_xdc else "") + ext
        p = filedialog.asksaveasfilename(title="Save as " + ext, defaultextension=ext, initialfile=base,
                                         filetypes=[("Xbox 360 texture", "*" + ext)])
        if not p:
            return
        if os.path.abspath(p) == os.path.abspath(self.src_path):
            if not messagebox.askyesno("Overwrite original?", "This replaces the original file. Continue?"):
                return
        data = make()
        if data is None:
            return
        open(p, "wb").write(data)
        self.status.set("Saved " + p)

    def save_xds(self):
        self._save_bytes(".xds", self._encoded_xds)

    def save_xdc(self):
        def make():
            x = self._encoded_xds()
            return None if x is None else T.pack_xdc(x)
        self._save_bytes(".xdc", make)

    # ---- drawing ----------------------------------------------------------
    def redraw(self):
        c = self.canvas
        c.delete("all")
        if self.rgba is None:
            return
        cw, ch = max(c.winfo_width(), 10), max(c.winfo_height(), 10)
        h, w = self.rgba.shape[:2]
        scale = min(cw / w, ch / h, 1.0)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        small = np.asarray(Image.fromarray(self.rgba).resize((nw, nh), Image.LANCZOS))
        if self.ignore_alpha.get():
            shown = small[..., :3]
        else:
            a = small[..., 3:4].astype(np.float32) / 255.0
            shown = (small[..., :3] * a + checkerboard(nw, nh) * (1 - a)).astype(np.uint8)
        self.photo = ImageTk.PhotoImage(Image.fromarray(shown))
        c.create_image(cw // 2, ch // 2, image=self.photo)


def main():
    root = tk.Tk()
    App(root, sys.argv[1] if len(sys.argv) > 1 else None)
    root.mainloop()


if __name__ == "__main__":
    main()
