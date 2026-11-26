"""J2B Studio — converts Java Edition mod assets into a Bedrock add-on.

Scope, stated plainly:

* **Converted** — blocks, items, crafting recipes and ore worldgen that have a
  faithful data equivalent on Bedrock.
* **Partial** — converted with documented losses (tool stats, tags, variants).
* **Manual** — entities, GUIs, particles, commands: the Java side is *code*, so
  there is nothing to translate mechanically. Reported, with the steps needed.
* **Unsupported** — dimensions, keybinds, client hooks, smithing recipes.

The tool never emits a placeholder it cannot justify, and every claim it makes
is traceable to an entry in ``j2b/knowledge/entries.py``.
"""

from .version import __version__

__all__ = ["__version__"]
