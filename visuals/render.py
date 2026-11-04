#!/usr/bin/env python3
"""render README visuals: <name>.html (body class THEME) -> <name>-light.png + <name>-dark.png at 2x, window sized to content.
usage: python3 render.py [name ...]   (default: every *.html here)"""
import re, subprocess, sys, pathlib
CH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
here = pathlib.Path(__file__).parent
def chrome(*args):
    return subprocess.run([CH, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                           "--user-data-dir=/tmp/rv-chrome", *args], check=True, capture_output=True, text=True).stdout
names = sys.argv[1:] or [p.stem for p in here.glob("*.html") if not p.name.startswith(".")]
for src in names:
    tpl = (here / f"{src}.html").read_text()
    for th in ("light", "dark"):
        tmp = here / f".{src}-{th}.html"
        tmp.write_text(tpl.replace("THEME", th).replace("</body>",
            "<script>document.title='H'+Math.ceil(document.body.getBoundingClientRect().height)</script></body>"))
        h = int(re.search(r"<title>H(\d+)</title>", chrome("--window-size=1600,900", "--dump-dom", tmp.as_uri())).group(1))
        out = here / f"{src}-{th}.png"
        chrome("--force-device-scale-factor=2", f"--window-size=1600,{h}", f"--screenshot={out}", tmp.as_uri())
        tmp.unlink()
        print(out.name, "1600x%d css px" % h)
