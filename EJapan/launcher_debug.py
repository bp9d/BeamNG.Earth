#!/usr/bin/env python3
"""Start BeamNG.drive with Lua debug mode (lrdb-beamng, port 21110) for debugging the mod's Lua
from VS Code. The world server is started separately from VS Code ("Python Server Launch (earthd)"
in .vscode/launch.json), so this script only launches the game.

    python EJapan/launcher_debug.py          # start the game with -lua-debug on -lua-debug-port 21110

Then attach with VS Code's "BeamNG Lua Attach" (Run and Debug, port 21110). The game's own
launcher (BeamNG.drive.exe) is started directly with the debug args, so Steam's launch options
are not needed.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import install  # noqa: E402
import launcher  # noqa: E402


def main():
    cfg = install.load_config()
    user_dir = cfg.get("user_dir")
    if not user_dir:
        found = install.candidate_user_dirs()
        user_dir = found[0] if found else None
    if not user_dir:
        install.fail("no BeamNG.drive user folder known. Run the installer first: python install.py")

    # the game's extra args (launcher.start_game reads BNGE_GAME_ARGS): Lua debug mode for lrdb-beamng
    os.environ["BNGE_GAME_ARGS"] = "-lua-debug on -lua-debug-port 21110"
    launcher.start_game(True, "native", "", user_dir)
    print("BeamNG.drive started with Lua debug (port 21110).")
    print("Attach with VS Code's 'BeamNG Lua Attach' (Run and Debug).")


if __name__ == "__main__":
    main()
