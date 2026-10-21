"""Team gold purchases. Call under the same lock/storage transaction as betting."""
import re
import secrets
import time
import uuid

PEPAZO_PRICE = 70
# Shared by all clients of this server version; a deploy/restart deals a new order.
QUOTE_SEED = secrets.randbits(32)


def public_shop(db, team_id=None):
    duo = next((d for d in db.get('duos', []) if d.get('id') == team_id), None)
    state = db.get('betting', {})
    wallet = state.get('wallets', {}).get(team_id) if duo else None
    return {'product': {'id': 'pepazo', 'name': 'Pepazo', 'unitPrice': PEPAZO_PRICE}, 'quoteSeed': QUOTE_SEED,
            'wallet': {'teamId': team_id, 'teamName': duo.get('teamName', ''),
                       'balance': wallet['balance'], 'inventory': duo.get('blueShells', 0),
                       'reserved': sum(b['amount'] for b in state.get('bets', [])
                                       if b['teamId'] == team_id and b['status'] == 'PENDING')}
                      if wallet else None}


def purchase(db, team_id, body, now=None):
    """Debit and credit together; retries return their original persisted receipt."""
    duo = next((d for d in db.get('duos', []) if d.get('id') == team_id), None)
    if not duo:
        raise PermissionError('Inicia sesión con tu equipo para comprar.')
    request_id = body.get('requestId')
    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', request_id):
        raise ValueError('Falta el identificador de compra. Recarga la página.')
    quantity = body.get('quantity')
    if type(quantity) is not int or not 1 <= quantity <= 1000000:
        raise ValueError('Elige una cantidad entera de pepazos, como mínimo 1.')
    key = team_id + ':' + request_id
    previous = db.get('shop', {}).get('purchases', {}).get(key)
    if previous:
        if previous['quantity'] != quantity:
            raise FileExistsError('Ese envío ya se utilizó para otra cantidad.')
        return dict(previous)
    wallet = db['betting']['wallets'][team_id]
    total = quantity * PEPAZO_PRICE
    if wallet['balance'] < total:
        raise FileExistsError('No tienes suficiente oro disponible. Cada pepazo cuesta 70 monedas.')
    now = time.time() if now is None else now
    receipt = {'id': str(uuid.uuid4()), 'quantity': quantity, 'unitPrice': PEPAZO_PRICE,
               'total': total, 'createdAt': now}
    wallet['balance'] -= total
    duo['blueShells'] = duo.get('blueShells', 0) + quantity
    duo['shellsPurchasedTotal'] = duo.get('shellsPurchasedTotal', 0) + quantity
    db.setdefault('shop', {}).setdefault('purchases', {})[key] = receipt
    db['betting']['ledger'].append({'id': 'shop:' + receipt['id'], 'kind': 'SHOP_PURCHASE',
        'teamId': team_id, 'amount': -total, 'quantity': quantity, 'purchaseId': receipt['id'], 'at': now})
    return dict(receipt)
