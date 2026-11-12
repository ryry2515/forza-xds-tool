# forza-xds-tool

A small Windows window for **Forza Horizon 1 `.xds` textures and `.xdc` profile thumbnails** (Xbox 360 formats): open one, see it as a picture, save it as a PNG, convert `.xdc` to `.xds` and back, and put an edited PNG back into an `.xds` or `.xdc`.

## Download (no Python)

Get `ForzaXdsTool-0.2.0-windows.zip` from the [Releases page](https://github.com/ryry2515/forza-xds-tool/releases/latest), extract it and run `ForzaXdsTool.exe`. Windows may warn about an unknown publisher because the exe is not code-signed.

## Use it from source

1. Install [Python 3](https://www.python.org/downloads/) and then, once: `pip install numpy pillow`
2. Run `python xds_gui.py` (or `python xds_gui.py some.xds`).
3. **Open .xds...** shows a texture or a profile thumbnail (`.xdc`). **Save as PNG...** writes it out.
4. To put an edit back: edit the PNG (keep the exact same width and height), click **Load edited PNG...**, then **Save as .xds...** or **Save as .xdc...**.
5. To just convert, open an `.xdc` and click **Save as .xds...** (or the other way round).

Command line, no window:

```
python xds_tool.py in.xds out.png          # also works for .xdc
python xds_tool.py in.xdc out.xds          # unpack a profile thumbnail
python xds_tool.py in.xds out.xdc          # pack it back
python xds_tool.py encode edited.png original.xds|xdc new.xds|xdc
```

## What works

- Reads DXT5 (car bodies, interiors, wheels), 8888 (UI, thumbnails) and `.xdc` (compressed thumbnails). DXT1 and DXT3 are in the code but untested.
- Saving to `.xds` works for DXT5 and 8888. It reuses the original file's header, so the size must match. DXT5 saving recompresses the base level and all mips down to 32 px; the tiny tail mips are copied from the original.
- Recompressing an already compressed DXT5 texture loses a little quality (about 31-33 dB PSNR). Edit once, from the original, and avoid saving the same texture many times over.
- **Edited `.xds` files have not been tested inside the game yet.** The file sizes, header and layout match the originals.
- Mips below the base level are not shown (only the full-size picture).

## About `.xdc`

`.xdc` is a compressed `.xds` (the Profile thumbnails the game keeps in `Thumbnails/Thumbnail_<n>.xdc`): a `cxds` header, then raw-deflate chunks that unpack to a normal `.xds` file. In one set of 202 sample saves, 130 thumbnails were real pictures and 72 held noise inside the file itself; the window warns when a file looks like that.

## Notes

- This tool contains no game files. You need your own copy of the game.
- Not affiliated with or endorsed by the game's makers.
- The `.xds` file format notes behind this tool are written up in the project's research notes.

MIT license.
