import re

from flask import Blueprint, request

import models
from .api_common import api_error, api_response
from .shop import MAX_QUANTITY


api_orders_bp = Blueprint('api_orders', __name__, url_prefix='/api')

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
MAX_ORDER_ITEMS = 50


def _order_to_dict(order, items=None):
    result = dict(order)
    if items is not None:
        result['items'] = [dict(item) for item in items]
    return result


def _read_order_data(data):
    """Validate a JSON order and convert its item list to the model cart map."""
    if not isinstance(data, dict):
        return None, {'body': 'Тіло запиту має бути JSON-об’єктом.'}

    errors = {}
    customer_name = data.get('customer_name')
    if not isinstance(customer_name, str) or not customer_name.strip():
        errors['customer_name'] = 'Вкажіть ім’я покупця.'
    elif len(customer_name.strip()) > 100:
        errors['customer_name'] = 'Ім’я не має перевищувати 100 символів.'

    email = data.get('email')
    if not isinstance(email, str) or not EMAIL_RE.fullmatch(email.strip()):
        errors['email'] = 'Вкажіть коректну електронну адресу.'
    elif len(email.strip()) > 254:
        errors['email'] = 'Email не має перевищувати 254 символи.'

    address = data.get('address')
    if not isinstance(address, str) or not address.strip():
        errors['address'] = 'Вкажіть адресу доставки.'
    elif len(address.strip()) > 500:
        errors['address'] = 'Адреса не має перевищувати 500 символів.'

    items = data.get('items')
    cart = {}
    if not isinstance(items, list) or not items:
        errors['items'] = 'Додайте принаймні один товар до замовлення.'
    elif len(items) > MAX_ORDER_ITEMS:
        errors['items'] = f'Замовлення може містити не більше {MAX_ORDER_ITEMS} позицій.'
    else:
        for index, item in enumerate(items):
            item_key = f'items[{index}]'
            if not isinstance(item, dict):
                errors[item_key] = 'Позиція має бути JSON-об’єктом.'
                continue

            product_id = item.get('product_id')
            quantity = item.get('quantity')
            if isinstance(product_id, bool) or not isinstance(product_id, int) or product_id <= 0:
                errors[f'{item_key}.product_id'] = 'ID товару має бути додатним цілим числом.'
                continue
            if isinstance(quantity, bool) or not isinstance(quantity, int):
                errors[f'{item_key}.quantity'] = 'Кількість має бути цілим числом.'
                continue
            if not 1 <= quantity <= MAX_QUANTITY:
                errors[f'{item_key}.quantity'] = f'Кількість має бути від 1 до {MAX_QUANTITY}.'
                continue

            combined_quantity = cart.get(product_id, 0) + quantity
            if combined_quantity > MAX_QUANTITY:
                errors[f'{item_key}.quantity'] = (
                    f'Загальна кількість одного товару не може перевищувати {MAX_QUANTITY}.'
                )
            else:
                cart[product_id] = combined_quantity

    promo_code = data.get('promo_code', '')
    if not isinstance(promo_code, str):
        errors['promo_code'] = 'Код промокоду має бути текстом.'
    elif len(promo_code.strip()) > 50:
        errors['promo_code'] = 'Код промокоду не має перевищувати 50 символів.'

    if errors:
        return None, errors

    return {
        'customer_name': customer_name.strip(),
        'email': email.strip(),
        'address': address.strip(),
        'cart': cart,
        'promo_code': promo_code.strip(),
    }, None


@api_orders_bp.get('/v1/orders')
@api_orders_bp.get('/v2/orders')
def list_orders():
    """Return all orders, newest first."""
    return api_response([_order_to_dict(order) for order in models.get_orders()])


@api_orders_bp.get('/v1/orders/<int:order_id>')
@api_orders_bp.get('/v2/orders/<int:order_id>')
def get_order(order_id):
    """Return one order and its product line items."""
    order, items = models.get_order_details(order_id)
    if order is None:
        return api_error('Замовлення не знайдено.', 404)
    return api_response(_order_to_dict(order, items))


@api_orders_bp.post('/v1/orders')
@api_orders_bp.post('/v2/orders')
def create_order():
    """Create an order from customer details and a list of product quantities."""
    data, errors = _read_order_data(request.get_json(silent=True))
    if errors:
        return api_error('Некоректні дані замовлення.', 400, errors)

    products = models.get_products_by_ids(data['cart'].keys())
    products_by_id = {product['id']: product for product in products}
    missing_ids = sorted(set(data['cart']) - set(products_by_id))
    if missing_ids:
        return api_error(
            'Одного або кількох товарів не знайдено.',
            400,
            {'product_ids': missing_ids},
        )

    unavailable_ids = sorted(
        product_id
        for product_id, product in products_by_id.items()
        if not product['is_available']
    )
    if unavailable_ids:
        return api_error(
            'Одного або кількох товарів немає в наявності.',
            409,
            {'product_ids': unavailable_ids},
        )

    try:
        order_id = models.create_order(
            data['customer_name'],
            data['email'],
            data['address'],
            data['cart'],
            promo_code=data['promo_code'],
        )
    except ValueError as error:
        return api_error(str(error), 400)

    order, items = models.get_order_details(order_id)
    response, status = api_response(_order_to_dict(order, items), 201)
    version_prefix = '/api/v2' if request.path.startswith('/api/v2/') else '/api/v1'
    response.headers['Location'] = f'{version_prefix}/orders/{order_id}'
    return response, status


@api_orders_bp.patch('/v1/orders/<int:order_id>')
@api_orders_bp.patch('/v2/orders/<int:order_id>')
def update_order_status(order_id):
    """Change an order's status without replacing the rest of the order."""
    order = models.get_order(order_id)
    if order is None:
        return api_error('Замовлення не знайдено.', 404)

    data = request.get_json(silent=True)
    status = data.get('status') if isinstance(data, dict) else None
    if status not in models.ORDER_STATUSES:
        return api_error(
            'Невідомий статус замовлення.',
            400,
            {'allowed_statuses': list(models.ORDER_STATUSES)},
        )

    models.update_order_status(order_id, status)
    updated_order, items = models.get_order_details(order_id)
    return api_response(_order_to_dict(updated_order, items))
