# -*- coding: utf-8 -*-
"""AES-GCM URL tokens for Worldpay result success/failure keys (24h)."""
import base64
import hashlib
import logging
import os
import struct
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from odoo import api, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

TOKEN_VERSION = 1
PURPOSE_WP_SUCCESS = 3
PURPOSE_WP_FAILURE = 4
PURPOSE_NAMES = {
    PURPOSE_WP_SUCCESS: 'wp_success',
    PURPOSE_WP_FAILURE: 'wp_failure',
}
TTL_RESULT_SECONDS = 24 * 3600
_KEY_PREFIX = b'neatworldpay-url-v1'
SEALED_MARKER = 'sealed:v1'


class NeatWorldpayUrlToken(models.AbstractModel):
    _name = 'neatworldpay.url.token'
    _description = 'NeatWorldpay Encrypted Result URL Token'

    @api.model
    def _database_secret(self):
        return (self.env['ir.config_parameter'].sudo().get_param('database.secret') or '').encode()

    @api.model
    def _aes_key(self):
        return hashlib.sha256(_KEY_PREFIX + self._database_secret()).digest()

    @api.model
    def amount_to_minor_units(self, amount, currency):
        digits = currency.decimal_places if currency else 2
        return int(round(float(amount) * (10 ** digits)))

    @api.model
    def _purpose_code(self, purpose):
        if isinstance(purpose, int):
            return purpose
        if purpose == 'wp_success':
            return PURPOSE_WP_SUCCESS
        if purpose == 'wp_failure':
            return PURPOSE_WP_FAILURE
        raise ValidationError('Invalid NeatWorldpay URL token purpose.')

    @api.model
    def seal(self, purpose, reference, amount, currency, ttl_seconds=None):
        """Return base64url token (no padding). purpose: 'wp_success'|'wp_failure'|int."""
        purpose = self._purpose_code(purpose)
        if purpose not in (PURPOSE_WP_SUCCESS, PURPOSE_WP_FAILURE):
            raise ValidationError('Invalid NeatWorldpay URL token purpose.')
        reference = (reference or '').encode('utf-8')
        if not reference or len(reference) > 255:
            raise ValidationError('Invalid NeatWorldpay URL token reference.')
        if ttl_seconds is None:
            ttl_seconds = TTL_RESULT_SECONDS
        currency_code = ((currency.name if currency else 'XXX') or 'XXX')[:3].ljust(3).encode('ascii')
        amount_cents = self.amount_to_minor_units(amount, currency)
        exp = int(time.time()) + int(ttl_seconds)
        plaintext = struct.pack(
            '>BBIq3sB',
            TOKEN_VERSION,
            purpose,
            exp,
            amount_cents,
            currency_code,
            len(reference),
        ) + reference
        nonce = os.urandom(12)
        token = AESGCM(self._aes_key()).encrypt(nonce, plaintext, None)
        return base64.urlsafe_b64encode(nonce + token).decode('ascii').rstrip('=')

    @api.model
    def open(self, token, expected_purpose=None):
        """Decrypt token. Returns dict or raises ValidationError."""
        if not token:
            raise ValidationError('Missing NeatWorldpay URL token.')
        raw = token.encode('ascii') if isinstance(token, str) else token
        pad = b'=' * (-len(raw) % 4)
        try:
            blob = base64.urlsafe_b64decode(raw + pad)
        except Exception as exc:
            raise ValidationError('Invalid NeatWorldpay URL token encoding.') from exc
        if len(blob) < 12 + 16 + 1:
            raise ValidationError('Invalid NeatWorldpay URL token.')
        nonce, ciphertext = blob[:12], blob[12:]
        try:
            plaintext = AESGCM(self._aes_key()).decrypt(nonce, ciphertext, None)
        except Exception as exc:
            raise ValidationError('Invalid NeatWorldpay URL token.') from exc
        if len(plaintext) < 1 + 1 + 4 + 8 + 3 + 1:
            raise ValidationError('Invalid NeatWorldpay URL token payload.')
        version, purpose, exp, amount_cents, currency_code, id_len = struct.unpack(
            '>BBIq3sB', plaintext[:18]
        )
        if version != TOKEN_VERSION:
            raise ValidationError('Unsupported NeatWorldpay URL token version.')
        if expected_purpose is not None:
            expected = self._purpose_code(expected_purpose)
            if purpose != expected:
                raise ValidationError('NeatWorldpay URL token purpose mismatch.')
        if int(time.time()) > int(exp):
            raise ValidationError('NeatWorldpay URL token expired.')
        reference = plaintext[18:18 + id_len].decode('utf-8')
        if len(plaintext) != 18 + id_len:
            raise ValidationError('Invalid NeatWorldpay URL token payload length.')
        return {
            'purpose': PURPOSE_NAMES.get(purpose, purpose),
            'purpose_code': purpose,
            'exp': exp,
            'amount_cents': amount_cents,
            'currency': currency_code.decode('ascii').strip(),
            'reference': reference,
        }

    @api.model
    def record_amount_matches(self, claims, amount, currency, tolerance_cents=0):
        if not claims or amount is None or not currency:
            return False
        if (currency.name or '').upper() != (claims.get('currency') or '').upper():
            return False
        expected = self.amount_to_minor_units(amount, currency)
        return abs(int(expected) - int(claims['amount_cents'])) <= int(tolerance_cents)
