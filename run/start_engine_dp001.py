"""Starts the ACCEPTED footing-repair engine (unmodified copy) server with the DP-001 human-prepared scope as the demo project source.
The engine tree is not edited: only integration.SCOPE_PATH is pointed at the DP-001 scope file before serving."""
import os, pathlib, sys
WS = pathlib.Path(__file__).resolve().parent.parent
os.chdir(WS); sys.path.insert(0, str(WS)); sys.dont_write_bytecode = True
from engine import integration            # noqa: E402
integration.SCOPE_PATH = WS / "dp001/scope_dp001_footing.json"
from api import server                    # noqa: E402
server.main()
