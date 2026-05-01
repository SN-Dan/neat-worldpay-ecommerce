# -*- coding: utf-8 -*-
import uuid

from odoo import api, fields, models
from passlib.context import CryptContext


class WorldpayPaymentLink(models.Model):
    _name = 'worldpay.payment.link'
    _description = 'WorldPay Payment Link'
    _rec_name = 'reference'

    reference = fields.Char(string='Reference', required=True, default=lambda self: f"pl/{uuid.uuid4()}", index=True)
    provider_id = fields.Many2one('payment.provider', string='Payment Provider', required=True, index=True)
    status = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('cancel', 'Cancelled'),
        ('error', 'Error'),
    ], string='Status', required=True, default='draft', index=True)
    invoice_ids = fields.Many2many('account.move', string='Invoices', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', compute='_compute_currency_and_total', store=True)
    amount_total = fields.Monetary(string='Total Amount', currency_field='currency_id', compute='_compute_currency_and_total', store=True)
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

    @api.depends('invoice_ids', 'invoice_ids.amount_residual', 'invoice_ids.currency_id')
    def _compute_currency_and_total(self):
        for rec in self:
            currency = rec.invoice_ids[:1].currency_id
            rec.currency_id = currency
            rec.amount_total = sum(rec.invoice_ids.mapped('amount_residual'))

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
