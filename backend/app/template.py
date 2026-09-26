import re
from copy import deepcopy

FULL = re.compile(r"^\{\{([A-Za-z0-9_.:-]+)\}\}$")
ANY = re.compile(r"\{\{([A-Za-z0-9_.:-]+)\}\}")

def render_template(value, variables: dict):
    if isinstance(value, dict):
        return {k: render_template(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [render_template(v, variables) for v in value]
    if not isinstance(value, str):
        return value

    full = FULL.match(value)
    if full:
        key = full.group(1)
        if key not in variables:
            raise KeyError(f"Missing workflow variable: {key}")
        return deepcopy(variables[key])

    def repl(match):
        key = match.group(1)
        if key not in variables:
            raise KeyError(f"Missing workflow variable: {key}")
        return str(variables[key])

    return ANY.sub(repl, value)
