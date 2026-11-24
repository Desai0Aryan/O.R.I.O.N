"""Tools Orion can use. Each module adds its tools with agent.register(name, fn, doc)."""


def load_all(agent):
    from . import calc, clock, screen, study, system, web
    for mod in (web, calc, clock, study, system, screen):
        mod.register(agent)
