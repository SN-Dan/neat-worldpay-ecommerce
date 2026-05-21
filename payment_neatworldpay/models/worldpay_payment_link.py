# -*- coding: utf-8 -*-
import base64
import logging
import re
import requests
import uuid
from decimal import Decimal

from werkzeug import urls

from odoo import api, fields, models
from passlib.context import CryptContext

_logger = logging.getLogger(__name__)


class WorldpayPaymentLink(models.Model):
    _name = 'worldpay.payment.link'
    _description = 'WorldPay Payment Link'
    _rec_name = 'reference'

    reference = fields.Char(string='Reference', required=True, default=lambda self: f"pl/{uuid.uuid4()}", index=True)
    provider_id = fields.Many2one('payment.provider', string='Payment Provider', required=True, index=True)
    company_id = fields.Many2one('res.company', string='Company', related='provider_id.company_id', store=True, readonly=True)
    partner_id = fields.Many2one('res.partner', string='Customer', compute='_compute_payment_values', store=True)
    status = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('cancel', 'Cancelled'),
        ('error', 'Error'),
    ], string='Status', required=True, default='draft', index=True)
    invoice_ids = fields.Many2many('account.move', string='Invoices')
    sale_order_ids = fields.Many2many('sale.order', string='Sales Orders')
    currency_id = fields.Many2one('res.currency', string='Currency', compute='_compute_payment_values', store=True)
    amount_total = fields.Monetary(string='Total Amount', currency_field='currency_id', compute='_compute_payment_values', store=True)
    amount = fields.Monetary(string='Amount', currency_field='currency_id', compute='_compute_payment_values', store=True)
    token_id = fields.Many2one('payment.token', string='Payment Token')
    neatworldpay_validation_hash = fields.Char(string='Success Validation Hash', default=None)
    neatworldpay_failure_validation_hash = fields.Char(string='Failure Validation Hash', default=None)
    neatworldpay_validation_attempts = fields.Integer(string='Validation Attempts', default=0)
    _sql_constraints = [
        ('worldpay_payment_link_reference_uniq', 'unique(reference)', 'WorldPay payment link reference must be unique.'),
    ]
    _pwd_context = CryptContext(
        schemes=["pbkdf2_sha512", "plaintext"],
        deprecated="auto",
    )

    @api.depends(
        'invoice_ids', 'invoice_ids.amount_residual', 'invoice_ids.currency_id', 'invoice_ids.partner_id',
        'sale_order_ids', 'sale_order_ids.amount_total', 'sale_order_ids.currency_id', 'sale_order_ids.partner_id',
    )
    def _compute_payment_values(self):
        for rec in self:
            if rec.sale_order_ids:
                rec.currency_id = rec.sale_order_ids[:1].currency_id
                rec.partner_id = rec.sale_order_ids[:1].partner_id
                rec.amount_total = sum(rec.sale_order_ids.mapped('amount_total'))
            else:
                rec.currency_id = rec.invoice_ids[:1].currency_id
                rec.partner_id = rec.invoice_ids[:1].partner_id
                rec.amount_total = sum(rec.invoice_ids.mapped('amount_residual'))
            rec.amount = rec.amount_total

    def neatworldpay_generate_transaction_key(self):
        self.ensure_one()
        transaction_key = str(uuid.uuid4())
        self.write({'neatworldpay_validation_hash': self._pwd_context.hash(transaction_key)})
        return transaction_key

    def neatworldpay_generate_failure_transaction_key(self):
        self.ensure_one()
        failure_transaction_key = str(uuid.uuid4())
        self.write({'neatworldpay_failure_validation_hash': self._pwd_context.hash(failure_transaction_key)})
        return failure_transaction_key

    def neatworldpay_validate_transaction_key(self, transaction_key):
        self.ensure_one()
        if self.neatworldpay_validation_attempts >= 3 or not self.neatworldpay_validation_hash:
            return False
        is_valid = self._pwd_context.verify(transaction_key, self.neatworldpay_validation_hash)
        if not is_valid:
            self.write({'neatworldpay_validation_attempts': self.neatworldpay_validation_attempts + 1})
        return is_valid

    def neatworldpay_validate_failure_transaction_key(self, failure_transaction_key):
        self.ensure_one()
        if not self.neatworldpay_failure_validation_hash:
            return False
        return self._pwd_context.verify(failure_transaction_key, self.neatworldpay_failure_validation_hash)

    def neatworldpay_get_processing_values(self, provider=None, result_action=None):
        self.ensure_one()
        provider = provider or self.provider_id
        exec_code = None
        if provider.neatworldpay_cached_code:
            exec_code = provider.neatworldpay_cached_code
        elif provider.neatworldpay_activation_code:
            try:
                headers = {
                    "Referer": (provider.company_id.website or ""),
                    "Authorization": provider.neatworldpay_activation_code,
                }
                response = requests.get(
                    "https://api.sns-software.com/api/AcquirerLicense/code?version=v5",
                    headers=headers,
                    timeout=10,
                )
                if response.status_code == 200:
                    exec_code = response.text
                    provider.write({"neatworldpay_cached_code": exec_code})
                else:
                    _logger.error(f"Failed to fetch activation code: {response.status_code} - {response.text}")
            except requests.RequestException as e:
                _logger.error(f"Request error: {e}")

        pay_url = None
        billing_address = None
        if exec_code:
            local_context = {
                "tr": self,
                "processing_values": {
                    "reference": self.reference,
                    "amount": self.amount,
                    "currency_id": self.currency_id.id,
                    "partner_id": self.partner_id.id,
                },
                "Decimal": Decimal,
                "requests": requests,
                "base64": base64,
                "re": re,
                "urls": urls,
                "neat_worldpay_controller_result_action": result_action,
                "env": self.env,
                "fields": fields,
                "is_multi_payment_link": True,
            }
            exec(exec_code, {}, local_context)
            data = local_context.get("data") or {}
            pl = local_context.get("payload", False)
            pay_url = data.get("url")
            billing_address = local_context.get("billing_address")
            _logger.info(f"\n Worldpay Payload {pl} \n")
            _logger.info(f"\n Worldpay Response {data} \n")

        return {
            "payment_url": pay_url,
            "billing_address": billing_address,
            "neatworldpay_use_iframe": provider.neatworldpay_use_iframe,
        }
