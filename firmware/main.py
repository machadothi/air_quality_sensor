# Runs at every boot, after boot.py. Everything is in app.py; see README.md.
# To stop it: Ctrl+C in `mpremote` (or any serial terminal) gives the REPL.
import app

app.run()
