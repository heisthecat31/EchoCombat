"""Asset lookup over several roots: "overlay;extract" finds an asset in the first root that has it."""

import os


def path(root: str, folder: str, name: str) -> str:
    for r in root.split(";"):
        p = os.path.join(r, folder, name)
        if os.path.exists(p):
            return p
    return os.path.join(root.split(";")[-1], folder, name)
