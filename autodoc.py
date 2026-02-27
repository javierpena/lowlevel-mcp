"""Automatic documentation generation for command-line tools.

Provides documentation with Literal type expansion and
Annotated description extraction. Unlike inspect.signature() or pydoc,
this formats types in a more readable way for CLI help text:
- Expands Literal types to show all valid values as 'val1' | 'val2'
- Extracts and displays descriptions from Annotated types
- Formats parameters one per line for better readability
"""
import sys
import inspect
from typing import get_origin, get_args, Annotated, Literal
from inspect import getmembers, isfunction, stack

def _fmt_type(ann):
    if get_origin(ann) is Literal:
        vals = get_args(ann)
        return ' | '.join(repr(v) for v in vals)
    if get_origin(ann) is Annotated:
        return _fmt_type(get_args(ann)[0])
    return ann.__name__ if hasattr(ann, '__name__') else str(ann)

def _fmt_param(p):
    default_str = '' if p.default == inspect.Parameter.empty else f" = {repr(p.default)}"
    ann = p.annotation

    if ann == inspect.Parameter.empty:
        return [f"{p.name}{default_str}"]

    if get_origin(ann) is Annotated:
        args = get_args(ann)
        base_str = _fmt_type(args[0])
        desc = args[1] if len(args) > 1 else ''
        type_str = f": {base_str}"
        main_line = f"{p.name}{type_str}{default_str}"

        if desc:
            full_line = f"{main_line}  # {desc}"
            if len(full_line) > 99:
                return [main_line, f"\t# {desc}"]
            return [full_line]
        return [main_line]

    return [f"{p.name}: {_fmt_type(ann)}{default_str}"]

def mydoc(m=None):
    if not m:
        m = (dict((name, func) for name, func
                  in getmembers(sys.modules[__name__]))[stack()[1][3]])
    sig = inspect.signature(m)
    d = inspect.getdoc(m)
    prefix = f"{m.__module__}." if m.__module__ != '__main__' else ''
    if d:
        params = list(sig.parameters.values())
        if params:
            p_lines = [f"\n\t{line}" for p in params for line in _fmt_param(p)]
            ret_ann = sig.return_annotation
            if ret_ann != inspect.Signature.empty:
                ret_name = ret_ann.__name__ if hasattr(ret_ann, '__name__') else ret_ann
                ret = f" -> {ret_name}"
            else:
                ret = ''
            sig_fmt = f"({''.join(p_lines)}\n){ret}"
        else:
            sig_fmt = str(sig)
        print(f"\033[1m{prefix}{m.__name__}\033[0m{sig_fmt}\n\t{d.partition('\n')[0]}\n")

def show_autodoc(main_module):
    d = inspect.getdoc(main_module)
    if d:
        print(d)
        print()
    for m in getmembers(main_module):
        if (isfunction(m[1]) and m[1].__module__ == main_module.__name__
                and not m[0].startswith('_')):
            mydoc(m[1])
