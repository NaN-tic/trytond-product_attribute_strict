# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import product

module = 'product_attribute_strict'

def register():
    Pool.register(
        product.ProductAttributeSet,
        product.AttributeSetFieldTemplate,
        product.ProductAttribute,
        product.ProductAttributeSelectionOption,
        product.ProductAttributeAttributeSet,
        product.ProductProductAttribute,
        product.Template,
        product.Product,
        module=module, type_='model'
    )
