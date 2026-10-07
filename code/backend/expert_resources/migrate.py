"""Idempotent local control-store migration and seed, never touches school tables."""
from . import execution, rules, store

if __name__ == '__main__':
    store.initialize()
    rules.initialize()
    execution.initialize()
    print('Expert resource control store initialized; school tables unchanged.')
