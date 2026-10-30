# Contributing to WiiThemer Desktop

Thanks for helping! Here's how to contribute the most common things.

## Report a bug

[Open an issue](https://github.com/A-Hackers-Guide/wiithemer-desktop/issues/new/choose) and use the **Bug report** form. The single most useful thing to include is the **full text of the log panel** at the bottom of the app.

## Add or improve a translation

1. Copy an existing pack from [`app/lang/`](app/lang), for example `Español.json`, and rename it to your language's own name, for example `Italiano.json`.
2. Translate the **values** only. Keep the **keys** (the English text) exactly as they are. Leave out any key you don't want to translate; it will stay in English.
3. To test it without building, put the file in the `lang` folder inside your settings folder (**Help → Open settings folder**). Then choose it in **Settings → Language**.
4. Open a pull request that adds the file to `app/lang/`.

Keys you can translate are the exact English texts on buttons, labels, tabs, column headings and menu items. You can see them in the app.

## Add themes to the built-in catalog

The built-in list is [`app/catalog.json`](app/catalog.json) (with a copy in [`docs/catalog.json`](docs/catalog.json) for the website). Each entry looks like this:

```json
{ "name": "Display name", "file": "file_name.mym", "preview": "preview.avif", "regions": ["U", "E", "J", "K"] }
```

- `file` is relative to `catalog.base_url + catalog.mym_path`. Use `{r}` for files that differ by region (it's replaced by `u`/`e`/`j`/`k`).
- Only add themes that are hosted somewhere the creator allows. This repository doesn't host theme files.

## Change the code

- Everything lives in [`app/wiithemer_desktop.py`](app/wiithemer_desktop.py). It's plain Python with Tkinter, and Pillow is optional.
- Run it with `python app/wiithemer_desktop.py`.
- Run `python app/wiithemer_desktop.py --selftest` before opening a PR. CI runs the self-test on every platform. If you add a feature, add a check for it to `selftest()`.
- Keep new settings in `DEFAULT_SETTINGS`, so they show up in **Advanced (JSON)**, and document them in the README's "Every setting" tables.

## Releases

Maintainers push a `vX.Y.Z` tag. GitHub Actions builds every platform and publishes the release. See "How releases are made" in the README.

By contributing, you agree that your contributions are licensed under GPL-2.0.
