# -*- coding: utf-8 -*-
import base64
import logging
import re
import requests
import uuid
from decimal import Decimal

from werkzeug import urls

from odoo import api, fields, models
from odoo.exceptions import ValidationError
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
        Token = self.env['neatworldpay.url.token'].sudo()
        from odoo.addons.payment_neatworldpay.models.neatworldpay_url_token import SEALED_MARKER
        transaction_key = Token.seal('wp_success', self.reference, self.amount, self.currency_id)
        self.write({
            'neatworldpay_validation_hash': SEALED_MARKER,
            'neatworldpay_validation_attempts': 0,
        })
        return transaction_key

    def neatworldpay_generate_failure_transaction_key(self):
        self.ensure_one()
        Token = self.env['neatworldpay.url.token'].sudo()
        from odoo.addons.payment_neatworldpay.models.neatworldpay_url_token import SEALED_MARKER
        failure_transaction_key = Token.seal(
            'wp_failure', self.reference, self.amount, self.currency_id
        )
        self.write({'neatworldpay_failure_validation_hash': SEALED_MARKER})
        return failure_transaction_key

    def _neatworldpay_validate_sealed_or_hash(self, key, purpose, hash_field, bump_attempts=False):
        from odoo.addons.payment_neatworldpay.models.neatworldpay_url_token import SEALED_MARKER
        Token = self.env['neatworldpay.url.token'].sudo()
        stored = self[hash_field]
        try:
            claims = Token.open(key, expected_purpose=purpose)
            if claims.get('reference') != self.reference:
                if bump_attempts:
                    self.write({'neatworldpay_validation_attempts': self.neatworldpay_validation_attempts + 1})
                return False
            if not Token.record_amount_matches(claims, self.amount, self.currency_id):
                if bump_attempts:
                    self.write({'neatworldpay_validation_attempts': self.neatworldpay_validation_attempts + 1})
                return False
            return True
        except ValidationError:
            pass
        if not stored or stored == SEALED_MARKER:
            return False
        try:
            is_valid = self._pwd_context.verify(key, stored)
        except Exception:
            return False
        if not is_valid and bump_attempts:
            self.write({'neatworldpay_validation_attempts': self.neatworldpay_validation_attempts + 1})
        return is_valid

    def neatworldpay_validate_transaction_key(self, transaction_key):
        self.ensure_one()
        if self.neatworldpay_validation_attempts >= 3 or not self.neatworldpay_validation_hash:
            return False
        return self._neatworldpay_validate_sealed_or_hash(
            transaction_key, 'wp_success', 'neatworldpay_validation_hash', bump_attempts=True
        )

    def neatworldpay_validate_failure_transaction_key(self, failure_transaction_key):
        self.ensure_one()
        if not self.neatworldpay_failure_validation_hash:
            return False
        return self._neatworldpay_validate_sealed_or_hash(
            failure_transaction_key, 'wp_failure', 'neatworldpay_failure_validation_hash'
        )

    def neatworldpay_get_processing_values(self, provider=None, result_action=None):
        self.ensure_one()
        provider = provider or self.provider_id
        exec_code = provider.neatworldpay_get_exec_code()
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


        if pay_url:
            try:
                self.env['neatworldpay.finalise.payment'].sudo().ensure_draft(
                    self.reference,
                    provider,
                    self.amount,
                    self.currency_id,
                    'ecommerce',
                )
            except Exception:
                pass
        return {
            "payment_url": pay_url,
            "billing_address": billing_address,
            "neatworldpay_use_iframe": provider.neatworldpay_use_iframe,
        }

    def _get_sale_orders_payment_transaction(self):
        self.ensure_one()
        return self.env['payment.transaction'].sudo().search([
            ('reference', '=', self.reference),
        ], limit=1)

    def _create_sale_orders_payment_transaction(self):
        """Create payment.transaction for SO payment-link using the joint reference."""
        self.ensure_one()
        if not self.sale_order_ids:
            return self.env['payment.transaction']
        existing = self._get_sale_orders_payment_transaction()
        if existing:
            return existing

        vals = {
            'provider_id': self.provider_id.id,
            'reference': self.reference,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'partner_id': self.partner_id.id,
            'operation': 'online_direct',
            'sale_order_ids': [(6, 0, self.sale_order_ids.ids)],
        }
        payment_method = self.env['payment.method'].sudo().search([
            ('code', '=', self.provider_id.code),
        ], limit=1)
        if payment_method:
            vals['payment_method_id'] = payment_method.id
        return self.env['payment.transaction'].sudo().create(vals)

    def _run_sale_orders_payment_transaction_post_process(self, tx):
        # Default finalize disabled — use register payment flow instead.
        # tx._finalize_post_processing()
        return True

    def _register_document_payments(self, invoices):
        """Create payments via account.payment.register (same path for invoices / multi-SO)."""
        if not invoices:
            return self.env['account.payment']
        wizard_ctx = {
            'active_model': 'account.move',
            'active_ids': invoices.ids,
            'active_id': invoices.ids[0],
        }
        register_vals = {}
        if self.provider_id.journal_id:
            register_vals['journal_id'] = self.provider_id.journal_id.id
        if getattr(self, 'is_partial', False):
            register_vals['amount'] = self.amount
            register_vals['group_payment'] = False
        else:
            register_vals['group_payment'] = True
        wizard = self.env['account.payment.register'].sudo().with_context(**wizard_ctx).create(register_vals)
        return wizard._create_payments()

    def _complete_invoices_payment(self):
        # Capture before register payment zeros residuals / recomputed amount.
        amount = self.amount
        currency = self.currency_id
        invoices = self.invoice_ids.filtered(lambda m: m.state == 'posted' and m.payment_state != 'paid')
        if invoices:
            self._register_document_payments(invoices)
        # Invoice-only docs never _set_done on a payment.transaction — queue finalise here.
        # Same value as license orderId: tr.reference (payment link reference).
        try:
            self.env['neatworldpay.finalise.payment'].sudo().mark_pending(
                self.reference,
                self.provider_id,
                amount,
                currency,
                'ecommerce',
            )
        except Exception:
            pass
        return True

    def _complete_multi_sale_orders_like_invoices(self, tx):
        """Confirm/invoice SOs if needed, then register onto unpaid invoices (same as invoice flow)."""
        for order in self.sale_order_ids.filtered(lambda o: o.state in ('draft', 'sent')):
            order.with_context(send_email=True).action_confirm()

        orders = self.sale_order_ids.filtered(lambda o: o.state == 'sale')
        if not orders:
            tx.is_post_processed = True
            return True

        # Further partials: pay residual on existing invoices (do not rely on _create_invoices).
        unpaid = orders.mapped('invoice_ids').filtered(
            lambda m: m.state == 'posted' and m.move_type == 'out_invoice' and m.payment_state != 'paid'
        )
        if not unpaid:
            orders._force_lines_to_invoice_policy_order()
            invoices = orders.with_context(raise_if_nothing_to_invoice=False)._create_invoices(final=True)
            draft_invoices = invoices.filtered(lambda m: m.state == 'draft')
            if draft_invoices:
                draft_invoices.action_post()
            unpaid = invoices.filtered(lambda m: m.state == 'posted' and m.payment_state != 'paid')

        if unpaid:
            payments = self._register_document_payments(unpaid)
            if payments and not tx.payment_id:
                tx.payment_id = payments[:1].id
            tx.invoice_ids = [(6, 0, unpaid.ids)]

        tx.is_post_processed = True
        return True

    def _complete_sale_orders_payment_transaction(self):
        self.ensure_one()
        if self.sale_order_ids:
            tx = self._get_sale_orders_payment_transaction()
            if not tx:
                return False
            if tx.state != 'done':
                tx._set_done()
            if tx.is_post_processed:
                return True
            # Finalize disabled — always use register payment flow.
            # self._run_sale_orders_payment_transaction_post_process(tx)
            return self._complete_multi_sale_orders_like_invoices(tx)
        if self.invoice_ids:
            return self._complete_invoices_payment()
        return False

    def _cancel_sale_orders_payment_transaction(self):
        self.ensure_one()
        tx = self._get_sale_orders_payment_transaction()
        if not tx or tx.state in ('done', 'cancel'):
            return False
        tx._set_canceled()
        return True
