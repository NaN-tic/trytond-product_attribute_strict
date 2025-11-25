# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
import pytz
from trytond.model import ModelSQL, ModelView, fields
from trytond.pool import PoolMeta, Pool
from trytond.pyson import Eval, If, Bool, Not
from trytond.transaction import Transaction

try:
    from jinja2 import Template as Jinja2Template
    jinja2_loaded = True
except ImportError:
    jinja2_loaded = False


ATTRIBUTE_TYPES = [
    ('boolean', 'Boolean'),
    ('integer', 'Integer'),
    ('char', 'Char'),
    ('float', 'Float'),
    ('numeric', 'Numeric'),
    ('date', 'Date'),
    ('datetime', 'DateTime'),
    ('selection', 'Selection'),
]

def datetime_to_company_tz(value):
    pool = Pool()
    Company = pool.get('company.company')
    Lang = pool.get('ir.lang')

    company_id = Transaction().context.get('company')
    if company_id:
        company = Company(company_id)
        if company.timezone:
            timezone = pytz.timezone(company.timezone)
            value = timezone.localize(value)
            value = value + value.utcoffset()
    return Lang.get().strftime(value)


class ProductAttributeSet(ModelSQL, ModelView):
    "Product Attribute Set"
    __name__ = 'product.attribute.set'

    name = fields.Char('Name', required=True, translate=True)
    fill_on_selection = fields.Boolean('Fill on Selection',
        help='If checked, the attributes will be created '
        'when the set is selected in a product.')
    attributes = fields.Many2Many(
        'product.attribute-product.attribute-set',
        'attribute_set', 'attribute', 'Attributes'
    )
    use_templates = fields.Boolean('Use Templates')
    jinja_templates = fields.One2Many('product.attribute.field_template',
        'attribute_set', 'Templates',
        states={
            'invisible': Not(Eval('use_templates'))
        })

    @staticmethod
    def default_use_templates():
        return False

    @staticmethod
    def template_context(record):
        User = Pool().get('res.user')
        user = None
        if Transaction().user:
            user = User(Transaction().user)
        return {
            'record': record,
            'user': user,
            }

    def render_expression(self, expression, attributes):
        record = dict((x.attribute.name, x.value) for x in attributes)
        template = Jinja2Template(expression)
        return template.render(record)

    def render_expression_record(self, expression, record):
        template = Jinja2Template(expression)
        return template.render(record)


class AttributeSetFieldTemplate(ModelSQL, ModelView):
    "Product Attribute field Templates"
    __name__ = 'product.attribute.field_template'

    field_ = fields.Selection('get_field_selection', 'Field')
    jinja_template = fields.Text('jinja_template')
    attribute_set = fields.Many2One('product.attribute.set', 'Attribute Set')

    @staticmethod
    def get_field_selection():
        return [
            ('product,code', 'Code'),
            ('template,name', 'Name')
        ]


class ProductAttributeSelectionOption(ModelSQL, ModelView):
    "Attribute Selection Option"

    __name__ = 'product.attribute.selection_option'

    name = fields.Char("Name", required=True, translate=True)
    attribute = fields.Many2One(
        "product.attribute", "Attribute", required=True, ondelete='CASCADE'
    )


class ProductAttribute(ModelSQL, ModelView):
    "Product Attribute"
    __name__ = 'product.attribute'

    sets = fields.Many2Many(
        'product.attribute-product.attribute-set',
        'attribute', 'attribute_set', 'Sets'
    )

    name = fields.Char('Name', required=True, translate=True)
    display_name = fields.Char('Display Name', translate=True)
    type_ = fields.Selection(
        ATTRIBUTE_TYPES, 'Type', required=True
    )

    selection = fields.One2Many(
        "product.attribute.selection_option", "attribute", "Selection",
        states={
            'invisible': ~(Eval('type_') == 'selection'),
        }
    )

    def get_rec_name(self, name):
        return self.display_name or self.name

    @staticmethod
    def default_type_():
        return 'char'


class ProductAttributeAttributeSet(ModelSQL):
    "Product Attribute - Set"
    __name__ = 'product.attribute-product.attribute-set'

    attribute = fields.Many2One(
        'product.attribute', 'Attribute',
        ondelete='CASCADE', required=True
    )
    attribute_set = fields.Many2One(
        'product.attribute.set', 'Set',
        ondelete='CASCADE', required=True
    )


class Template(metaclass=PoolMeta):
    __name__ = 'product.template'

    attribute_set = fields.Many2One('product.attribute.set', 'Set',
        ondelete='RESTRICT')
    attributes = fields.One2Many(
        "product.product.attribute", "template", "Attributes",
        domain=[
            ('attribute_set', '=',
                Eval('attribute_set')),
            ],
        states={
            'readonly': (~Eval('attribute_set')),
        })
    use_templates = fields.Function(fields.Boolean('Use Templates'),
        'get_use_templates')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
            'update_attributes_values': {
                'invisible': ~Eval('use_templates'),
                'depends': ['attribute_set', 'use_templates'],
                }
            })

    @fields.depends('attribute_set', 'attributes')
    def on_change_attribute_set(self):
        pool = Pool()
        ProductAttribute = pool.get('product.product.attribute')

        if not self.attribute_set or not self.attribute_set.fill_on_selection:
            return
        set_attributes = set(self.attribute_set.attributes)
        product_attributes = set([x.attribute for x in self.attributes])

        missing = set_attributes - product_attributes
        exceeding = product_attributes - set_attributes

        to_add = []
        for attribute in self.attributes:
            if attribute.attribute in exceeding:
                continue
            to_add.append(attribute)
        for attribute in missing:
            product_attribute = ProductAttribute()
            product_attribute.attribute = attribute
            product_attribute.attribute_type = attribute.type_
            product_attribute.value = product_attribute.on_change_with_value()
            to_add.append(product_attribute)
        self.attributes = tuple(to_add)

    def get_use_templates(self, name):
        if self.attribute_set and self.attribute_set.use_templates:
            return True
        return False

    def _update_attributes_values(self):
        products_to_save = []

        if (not self.attribute_set or
                not self.attribute_set.use_templates):
            return products_to_save

        for product in self.products:
            for field in self.attribute_set.jinja_templates:
                obj_name, name = field.field_.split(',')
                obj = self
                if obj_name == 'product' and product:
                    obj = product
                    products_to_save.append(product)

                jinja_template = field.jinja_template
                value = self.attribute_set.render_expression(
                    jinja_template, self.attributes)
                setattr(obj, name, value)

        return products_to_save

    @classmethod
    @ModelView.button
    def update_attributes_values(cls, templates):
        Product = Pool().get('product.product')
        product_to_save = []
        for template in templates:
            product_to_save += template._update_attributes_values()

        cls.save(templates)
        Product.save(product_to_save)

    @property
    def product_attribute_used(self):
        # Skip rules to test pattern on all records
        with Transaction().set_user(0):
            template = self.__class__(self)
        for attribute in template.attributes:
            yield attribute

    @classmethod
    def copy(cls, templates, default=None):
        pool = Pool()
        ProductAttribute = pool.get('product.product.attribute')
        if default is None:
            default = {}
        else:
            default = default.copy()

        copy_attributes = 'attributes' not in default
        default.setdefault('attributes', None)
        new_templates = super().copy(templates, default)
        if copy_attributes:
            old2new = {}
            to_copy = []
            for template, new_template in zip(templates, new_templates):
                to_copy.extend(
                    ps for ps in template.attributes if not ps.product)
                old2new[template.id] = new_template.id
            if to_copy:
                ProductAttribute.copy(to_copy, {
                        'template': lambda d: old2new[d['template']],
                        })
        return new_templates

class Product(metaclass=PoolMeta):
    __name__ = 'product.product'

    attributes = fields.One2Many(
        "product.product.attribute", "product", "Attributes",
        domain=[
            ('attribute_set', '=',
                Eval('product_attribute_set')),
            ],
        states={
            'readonly': (~Eval('product_attribute_set')),
        })

    product_attribute_set = fields.Function(fields.Many2One(
        'product.attribute.set', 'Attribute Set'), 'get_product_attribute_set')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
            'update_attributes_values': {
                'invisible': ~Eval('use_templates'),
                'depends': ['attribute_set', 'use_templates']}})

    def get_product_attribute_set(self, name=None):
        return self.template.attribute_set and self.template.attribute_set.id

    @classmethod
    @ModelView.button
    def update_attributes_values(cls, products):
        Template = Pool().get('product.template')
        templates = {x.template for x in products}
        Template.update_attributes_values(templates)

    @property
    def product_attribute_used(self):
        # Skip rules to test pattern on all records
        with Transaction().set_user(0):
            product = self.__class__(self)
        for attributes in product.attributes:
            yield attributes
        yield from self.template.product_attribute_used()

    @classmethod
    def copy(cls, products, default=None):
        pool = Pool()
        ProductAttribute = pool.get('product.product.attribute')
        if default is None:
            default = {}
        else:
            default = default.copy()

        copy_attributes = 'attributes' not in default
        if 'template' in default:
            default.setdefault('attributes', None)
        new_products = super().copy(products, default)
        if 'template' in default and copy_attributes:
            template2new = {}
            product2new = {}
            to_copy = []
            for product, new_product in zip(products, new_products):
                if product.attributes:
                    to_copy.extend(product.attributes)
                    template2new[product.template.id] = new_product.template.id
                    product2new[product.id] = new_product.id
            if to_copy:
                ProductAttribute.copy(to_copy, {
                        'product': lambda d: product2new[d['product']],
                        'template': lambda d: template2new[d['template']],
                        })
        return new_products


class ProductProductAttribute(ModelSQL, ModelView):
    "Product's Product Attribute"
    __name__ = 'product.product.attribute'

    template = fields.Many2One(
        "product.template", "Template", required=True,
        ondelete='CASCADE',
        domain=[
            If(Bool(Eval('product')),
                ('products', '=', Eval('product')),
                ()),
            ])
    product = fields.Many2One(
        "product.product", "Variant",
        domain=[
            If(Bool(Eval('template')),
                ('template', '=', Eval('template')),
                ()),
            ])
    attribute = fields.Many2One(
        "product.attribute", "Attribute", required=True,
        domain=[('sets', '=', Eval('attribute_set'))],
        ondelete='RESTRICT')
    attribute_type = fields.Function(
        fields.Selection(ATTRIBUTE_TYPES, "Attribute Type"),
        'on_change_with_attribute_type')
    attribute_set = fields.Function(
        fields.Many2One("product.attribute.set", "Attribute Set"),
        'on_change_with_attribute_set', searcher='search_attribute_set')
    value = fields.Function(fields.Char('Attribute Value'),
        getter='on_change_with_value')
    value_char = fields.Char(
        "Value Char", translate=True, states={
            'required': Eval('attribute_type') == 'char',
            'invisible': ~(Eval('attribute_type') == 'char'),
        })
    value_numeric = fields.Numeric(
        "Value Numeric", states={
            'required': Eval('attribute_type') == 'numeric',
            'invisible': ~(Eval('attribute_type') == 'numeric'),
        })
    value_float = fields.Float(
        "Value Float", states={
            'required': Eval('attribute_type') == 'float',
            'invisible': ~(Eval('attribute_type') == 'float'),
        })
    value_selection = fields.Many2One(
        "product.attribute.selection_option", "Value Selection",
        domain=[('attribute', '=', Eval('attribute'))],
        states={
            'required': Eval('attribute_type') == 'selection',
            'invisible': ~(Eval('attribute_type') == 'selection'),
        }, ondelete='RESTRICT')

    value_boolean = fields.Boolean(
        "Value Boolean", states={
            'invisible': ~(Eval('attribute_type') == 'boolean'),
        })
    value_integer = fields.Integer(
        "Value Integer", states={
            'required': Eval('attribute_type') == 'integer',
            'invisible': ~(Eval('attribute_type') == 'integer'),
        })
    value_date = fields.Date(
        "Value Date", states={
            'required': Eval('attribute_type') == 'date',
            'invisible': ~(Eval('attribute_type') == 'date'),
        })
    value_datetime = fields.DateTime(
        "Value Datetime", states={
            'required': Eval('attribute_type') == 'datetime',
            'invisible': ~(Eval('attribute_type') == 'datetime'),
        })

    @fields.depends('product', '_parent_product.template', 'attribute_set')
    def on_change_product(self):
        if self.product:
            self.template = self.product.template
            self.attribute_set = self.template.attribute_set

    @fields.depends('attribute')
    def on_change_with_attribute_type(self, name=None):
        if self.attribute:
            return self.attribute.type_

    @fields.depends('attribute_type', 'value_selection', 'value_datetime',
        'value_date', 'value_char', 'value_numeric', 'value_float',
        'value_boolean', 'value_integer')
    def on_change_with_value(self, name=None):
        Lang = Pool().get('ir.lang')

        if not self.attribute_type:
            return
        if self.attribute_type == 'selection':
            return self.value_selection and self.value_selection.name
        if self.attribute_type == 'datetime':
            return (self.value_datetime
                and datetime_to_company_tz(self.value_datetime))
        if self.attribute_type == 'date':
            if not self.value_date:
                return
            return Lang.get().strftime(self.value_date)
        else:
            value = getattr(self, 'value_' + self.attribute_type)
            return '%s' % value if value is not None else ''

    @fields.depends('template', '_parent_template.id',
        '_parent_template.attribute_set')
    def on_change_with_attribute_set(self, name=None):
        """
        Returns attribute set for corresponding product's template
        """
        if self.template and self.template.attribute_set:
            return self.template.attribute_set.id


    @classmethod
    def search_attribute_set(cls, name, clause):
        return [
            (('template.attribute_set',) + tuple(clause[1:])),
            ]
