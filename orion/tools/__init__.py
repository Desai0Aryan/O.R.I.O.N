"""Tools Orion can use. Each module adds its tools with agent.register(name, fn, doc)."""


def load_all(agent):
    from . import calc, study, web
    for mod in (web, calc, study):
        mod.register(agent)
