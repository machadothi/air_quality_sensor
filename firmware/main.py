# Runs at every boot, after boot.py. Everything is in app.py; see README.md.
# To stop it: Ctrl+C in `mpremote` (or any serial terminal) gives the REPL.
#
# If app.py itself can't be loaded (e.g. a broken update), restart instead of
# stopping at the REPL: boot.py then rolls the update back after two tries.
import sys
import time

try:   # a requested update check or install runs first, with the RAM still free
    import updater
    updater.maintenance()
except Exception as e:
    sys.print_exception(e)

try:
    import app
except Exception as e:   # not KeyboardInterrupt: Ctrl+C still reaches the REPL
    sys.print_exception(e)
    import machine
    time.sleep(10)
    machine.reset()

app.run()
