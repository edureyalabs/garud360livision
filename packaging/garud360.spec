# packaging/garud360.spec
# PyInstaller build:  pyinstaller packaging/garud360.spec --noconfirm
# Produces dist/Garud360LiVision/Garud360LiVision.exe (one-folder build, windowed).
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent

datas = [(str(ROOT / "assets" / "logo.png"), "assets"),
         (str(ROOT / "assets" / "logo_white.png"), "assets"),
         (str(ROOT / "assets" / "icon.ico"), "assets"),
         (str(ROOT / "docs"), "docs")]
binaries = []
hiddenimports = collect_submodules("garud360") + collect_submodules("asyncua") + collect_submodules("snap7") \
    + ["pymcprotocol", "pycomm3", "bcrypt"]

for pkg in ("ultralytics", "pycomm3", "pymcprotocol"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis([str(ROOT / "garud360" / "__main__.py")], pathex=[str(ROOT)], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
             excludes=["tkinter", "matplotlib.tests", "pytest", "IPython", "notebook"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Garud360LiVision", debug=False, strip=False, upx=False,
          console=False, icon=str(ROOT / "assets" / "icon.ico"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Garud360LiVision")
