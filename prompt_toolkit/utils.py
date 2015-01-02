from __future__ import unicode_literals

import six
from collections import defaultdict

try:
    from wcwidth import wcwidth
except ImportError:
    from .libs.wcwidth import wcwidth


__all__ = (
    'EventHook',
    'DummyContext',
)


class EventHook(object):
    """
    Event hook::

        e = EventHook()
        e += handler_function  # Add event handler.
        e.fire()  # Fire event.

    Thanks to Michael Foord:
    http://www.voidspace.org.uk/python/weblog/arch_d7_2007_02_03.shtml#e616
    """
    def __init__(self):
        self.__handlers = []

    def __iadd__(self, handler):
        self.__handlers.append(handler)
        return self

    def __isub__(self, handler):
        self.__handlers.remove(handler)
        return self

    def fire(self, *args, **keywargs):
        for handler in self.__handlers:
            handler(*args, **keywargs)


class DummyContext(object):
    """
    (contextlib.nested is not available on Py3)
    """
    def __enter__(self):
        pass

    def __exit__(self, *a):
        pass


class _CharSizesCache(dict):
    """
    Cache for wcwidth sizes.
    """
    def __missing__(self, character):
        result = wcwidth(character)
        self[character] = result
        return result

_CHAR_SIZES_CACHE = _CharSizesCache()

def get_cwidth(c):
    """
    Return width of character. Wrapper around ``wcwidth``.
    """
    return _CHAR_SIZES_CACHE[c]
