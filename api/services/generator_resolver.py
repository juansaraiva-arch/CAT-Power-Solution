"""
CAT Power Solution — Generator Resolver
=========================================
Resolves generator model names to full data dicts with optional overrides.
"""

from core.generator_library import get_library


def resolve_generator(model_name: str, overrides: dict | None = None) -> dict:
    """
    Look up a generator by library name and apply optional parameter overrides.

    Parameters
    ----------
    model_name : str
        Generator model name (e.g. "G3516H").
    overrides : dict, optional
        Key-value pairs to override in the generator data.

    Returns
    -------
    dict
        Full generator data dictionary.

    Raises
    ------
    KeyError
        If model_name is not found in the library.
    """
    lib = get_library()
    if model_name not in lib:
        raise KeyError(f"Generator model '{model_name}' not found in library. "
                       f"Available: {sorted(lib.keys())}")
    gen_data = lib[model_name]
    if overrides:
        for key, value in overrides.items():
            if key in gen_data:
                gen_data[key] = value
    return gen_data
