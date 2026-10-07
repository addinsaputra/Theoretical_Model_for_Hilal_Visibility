"""Schaefer-Kastner-Crumey crescent visibility calculations."""

__all__ = ['HilalVisibilityCalculator']


def __getattr__(name):
    if name == 'HilalVisibilityCalculator':
        from .calculator import HilalVisibilityCalculator
        return HilalVisibilityCalculator
    raise AttributeError(name)
