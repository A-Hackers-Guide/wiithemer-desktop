# WiiThemer Desktop

A cross-platform desktop port of [WiiThemer](https://github.com/scooby7402976/wiithemer) (release 1.0) by scooby7402976. It builds custom Wii System Menu theme files (`.csm`) from `.mym` theme mods.

**Website:** https://a-hackers-guide.github.io/wiithemer-desktop/

## Downloads

Grab them from [Releases](https://github.com/A-Hackers-Guide/wiithemer-desktop/releases/latest):

| Platform | File |
|---|---|
| Windows | `WiiThemerDesktop-Windows.exe` |
| macOS | `WiiThemerDesktop-macOS.dmg` or `WiiThemerDesktop-macOS.app.zip` (contains the `.app`) |
| Linux | `WiiThemerDesktop-Linux-x86_64.AppImage` |

The builds aren't code-signed. On macOS, right-click the app and choose **Open** the first time. On Linux, run `chmod +x` on the AppImage first.

## Requirements

The theme build step uses the original `themewii.exe`, which is a Windows .NET program.

- **Windows:** works out of the box (you need .NET Framework, which is usually already installed).
- **macOS / Linux:** install Wine with wine-mono (`brew install --cask wine-stable`, or `sudo apt install wine`). You can change the Wine command in Settings → Tools.

themewii downloads the System Menu file for your version. You can also point the app at your own NAND-dumped System Menu `.app` instead.

## You can customize everything

- **Theme source:** pick from the 73-theme catalog, open a local `.mym`, or add one by URL
- **Catalog:** change the base URL (to a fork or your own server), and hide or show themes
- **Build:** System Menu version and region, spin mod (nospin, spin, fastspin, transchan, or your own `.mym`), whether the spin is applied first, the output folder, and the file name template
- **Pipeline:** edit the exact themewii commands run for every build, and add extra System Menu versions (Advanced tab)
- **Tools:** use your own themewii.exe, set the Wine command, the key argument, and step timeouts
- **Appearance:** widget style, font, size, every color, preview size, and window title
- **MYM editor:** open, create, or edit `.mym` files (edit `mym.ini`, replace, extract, or add images), then save them and add them to your list
- **Settings:** import, export, or reset them, or edit them all as raw JSON

## Run from source

```
pip install -r requirements.txt
python app/wiithemer_desktop.py
```

## License

GPL-2.0, the same as the original WiiThemer. The `app/tools` binaries and spin mods come from the original repository. The themes and preview images are downloaded on demand from the original project and belong to their creators. This project is not affiliated with Nintendo. Modding your console is at your own risk.
