# Runs first at every boot. Keep it tiny: a mistake here can lock you out of
# the REPL. The application starts from main.py.
import gc

gc.collect()
