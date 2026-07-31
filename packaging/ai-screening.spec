# PyInstaller spec shared by the macOS and Windows builds.
# Build with:  pyinstaller packaging/ai-screening.spec --noconfirm
import sys
from pathlib import Path

# SPECPATH is injected by PyInstaller; the repo root is its parent.
ROOT = Path(SPECPATH).parent

# uvicorn resolves these by string at runtime, so PyInstaller's import graph
# never sees them and they have to be named explicitly.
HIDDEN = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "anthropic",
]

a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=[],
    # The SPA, its bundled typeface, and the font licence ship inside the app.
    datas=[(str(ROOT / "app" / "static"), "app/static")],
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "matplotlib", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AI Screening" if sys.platform == "darwin" else "AIScreeningAssistant",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # no terminal window behind the app
    icon=str(ROOT / "packaging" / "icons" / ("icon.icns" if sys.platform == "darwin" else "icon.ico")),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AI Screening" if sys.platform == "darwin" else "AIScreeningAssistant",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="AI Systematic Review Screening Assistant.app",
        icon=str(ROOT / "packaging" / "icons" / "icon.icns"),
        bundle_identifier="com.aiscreening.app",
        info_plist={
            # CFBundleName drives the macOS menu bar, which truncates past
            # roughly 30 characters, so the full title lives in DisplayName.
            "CFBundleName": "AI Screening Assistant",
            "CFBundleDisplayName": "AI Systematic Review Screening Assistant",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
            # Loopback only; no outside connections are made by the shell.
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
            "LSMinimumSystemVersion": "11.0",
        },
    )
