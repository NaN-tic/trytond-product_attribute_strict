# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
try:
    from trytond.modules.contract.tests.test_product_attribute_strict import suite
except ImportError:
    from .test_product_attribute_strict import suite

__all__ = ['suite']
