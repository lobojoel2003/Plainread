# PyInstaller spec for the one-file Plainread desktop app.
# Build with:  pyinstaller packaging/plainread.spec --noconfirm --clean
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

datas = collect_data_files("plainread")
datas += collect_data_files("pypdfium2_raw") + collect_data_files("pypdfium2")
datas += copy_metadata("plainread")
hiddenimports = collect_submodules("uvicorn") + collect_submodules("plainread")

a = Analysis(
    ["plainread_app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "numpy", "pytest", "playwright"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="plainread",
    console=True,
    upx=False,
    icon=None,
)
