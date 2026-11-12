# forza-xds-tool

A small Windows window for **Forza Horizon 1 `.xds` textures** (Xbox 360 format): open one, see it as a picture, save it as a PNG, and put an edited PNG back into an `.xds`.

## Use it

1. Install [Python 3](https://www.python.org/downloads/) and then, once: `pip install numpy pillow`
2. Run `python xds_gui.py` (or `python xds_gui.py some.xds`).
3. **Open .xds...** shows the texture. **Save as PNG...** writes it out.
4. To put an edit back: edit the PNG (keep the exact same width and height), click **Load edited PNG...**, then **Save as .xds...**.

Command line, no window:

```
python xds_tool.py in.xds out.png
python xds_tool.py encode edited.png original.xds new.xds
```

## What works

- Reads DXT5 (car bodies, interiors, wheels) and 8888 (UI, thumbnails). DXT1 and DXT3 are in the code but untested.
- Saving to `.xds` works for DXT5 and 8888. It reuses the original file's header, so the size must match. DXT5 saving recompresses the base level and all mips down to 32 px; the tiny tail mips are copied from the original.
- Recompressing an already compressed DXT5 texture loses a little quality (about 31-33 dB PSNR). Edit once, from the original, and avoid saving the same texture many times over.
- **Edited `.xds` files have not been tested inside the game yet.** The file sizes, header and layout match the originals.
- Mips below the base level are not shown (only the full-size picture).

## Notes

- This tool contains no game files. You need your own copy of the game.
- Not affiliated with or endorsed by the game's makers.
- The `.xds` file format notes behind this tool are written up in the project's research notes.

MIT license.
