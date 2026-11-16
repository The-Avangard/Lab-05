"""Versioned JSON API routes for products."""

import math
import sqlite3

from flask import Blueprint, request

import models
from .api_common import api_error, api_response


api_products_bp = Blueprint('api_products', __name__, url_prefix='/api')


def _product_to_dict(product):
    return {
        'id': product['id'],
        'category': product['category'],
        'name': product['name'],
        'description': product['description'],
        'specifications': product['specifications'],
        'price': product['price'],
        'image_url': product['image_url'],
        'is_available': bool(product['is_available']),
        'created_at': product['created_at'],
    }


def _validate_product_data(data):
    """Validate the fields accepted when creating or replacing a product."""
    if not isinstance(data, dict):
        return None, {'body': 'Надішліть JSON-об’єкт.'}

    errors = {}
    result = {}

    for field in ('category', 'name'):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            errors[field] = 'Поле обов’язкове і має бути текстом.'
        else:
            result[field] = value.strip()

    if result.get('category') not in models.PRODUCT_CATEGORIES:
        errors['category'] = (
            'Оберіть одну з категорій: ' + ', '.join(models.PRODUCT_CATEGORIES)
        )

    for field in ('description', 'specifications', 'image_url'):
        value = data.get(field, '')
        if not isinstance(value, str):
            errors[field] = 'Поле має бути текстом.'
        else:
            result[field] = value.strip()

    price = data.get('price')
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        errors['price'] = 'Ціна має бути числом.'
    elif not math.isfinite(price) or price < 0:
        errors['price'] = 'Ціна має бути скінченним числом не меншим за 0.'
    else:
        result['price'] = float(price)

    if errors:
        return None, errors
    return result, None


@api_products_bp.get('/v1/products')
@api_products_bp.get('/v2/products')
def list_products():
    """List available products. Optional filters: ``q`` and ``category``."""
    query = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()

    if category and category not in models.PRODUCT_CATEGORIES:
        return api_error(
            'Невідома категорія товару.',
            400,
            {'allowed_categories': list(models.PRODUCT_CATEGORIES)},
        )

    products = models.get_products(query=query, category=category)
    return api_response([_product_to_dict(product) for product in products])


@api_products_bp.get('/v1/products/<int:product_id>')
@api_products_bp.get('/v2/products/<int:product_id>')
def get_product(product_id):
    """Return one product by its ID."""
    product = models.get_product(product_id)
    if product is None:
        return api_error('Товар не знайдено.', 404)
    return api_response(_product_to_dict(product))


@api_products_bp.post('/v1/products')
@api_products_bp.post('/v2/products')
def create_product():
    """Create a product from a JSON object."""
    data, errors = _validate_product_data(request.get_json(silent=True))
    if errors:
        return api_error('Некоректні дані товару.', 400, errors)

    product_id = models.add_product(
        data['category'],
        data['name'],
        data['description'],
        data['specifications'],
        data['price'],
        data['image_url'],
    )
    product = models.get_product(product_id)
    return api_response(_product_to_dict(product), 201)


@api_products_bp.put('/v1/products/<int:product_id>')
@api_products_bp.put('/v2/products/<int:product_id>')
def replace_product(product_id):
    """Replace all editable fields of an existing product."""
    if models.get_product(product_id) is None:
        return api_error('Товар не знайдено.', 404)

    data, errors = _validate_product_data(request.get_json(silent=True))
    if errors:
        return api_error('Некоректні дані товару.', 400, errors)

    models.update_product(
        product_id,
        data['category'],
        data['name'],
        data['description'],
        data['specifications'],
        data['price'],
        data['image_url'],
    )
    return api_response(_product_to_dict(models.get_product(product_id)))


@api_products_bp.delete('/v1/products/<int:product_id>')
@api_products_bp.delete('/v2/products/<int:product_id>')
def remove_product(product_id):
    """Delete a product that is not referenced by an order."""
    if models.get_product(product_id) is None:
        return api_error('Товар не знайдено.', 404)

    try:
        models.delete_product(product_id)
    except sqlite3.IntegrityError:
        return api_error(
            'Не можна видалити товар, який уже входить до замовлення.', 409
        )

    return api_response(message='Товар видалено.')
