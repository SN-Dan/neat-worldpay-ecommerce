# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import json

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class WorldpayLinkPopup(models.TransientModel):
    _name = 'worldpay.link.popup'
    _description = 'WorldPay Link Popup'

    provider_id = fields.Many2one(
        'payment.provider',
        string='Payment Provider',
        required=True,
        domain="[('code', '=', 'neatworldpay'), ('state', '!=', 'disabled')]",
    )
    reference = fields.Char(string='Reference', readonly=True)
    payment_link = fields.Char(string='Payment Link', readonly=True)

    def _build_link_payload(self, link_rec):
        payload_data = {
            'link_id': link_rec.id,
            'reference': link_rec.reference,
            'provider_id': link_rec.provider_id.id,
        }
        payload_json = json.dumps(payload_data, separators=(',', ':')).encode()
        encoded_payload = base64.urlsafe_b64encode(payload_json).decode().rstrip('=')
        secret = (self.env['ir.config_parameter'].sudo().get_param('database.secret') or '').encode()
        signature = hmac.new(secret, encoded_payload.encode(), hashlib.sha256).hexdigest()
        return f'{encoded_payload}.{signature}'

    def _generate_link_values(self, provider=None):
        invoice_ids = self.env.context.get('active_ids', [])
        invoices = self.env['account.move'].sudo().browse(invoice_ids).exists()
        invoices = invoices.filtered(lambda m: m.is_invoice(include_receipts=False) and m.state == 'posted')
        if not invoices:
            raise ValidationError('Please select at least one posted customer invoice.')
        if any(inv.payment_state == 'paid' for inv in invoices):
            raise ValidationError('One or more selected invoices are already paid.')
        if len(invoices.mapped('currency_id')) > 1:
            raise ValidationError('All selected invoices must have the same currency.')
        if len(invoices.mapped('partner_id')) > 1:
            raise ValidationError('All selected invoices must belong to the same customer.')

        provider = provider or self.env['payment.provider'].sudo().search([
            ('code', '=', 'neatworldpay'),
            ('state', '!=', 'disabled'),
        ], limit=1)
        if not provider or not provider.neatworldpay_connection_url:
            raise ValidationError('Worldpay provider connection URL is not configured.')

        link_rec = self.env['worldpay.payment.link'].sudo().create({
            'provider_id': provider.id,
            'status': 'draft',
            'invoice_ids': [(6, 0, invoices.ids)],
        })
        payload = self._build_link_payload(link_rec)
        base_url = provider.neatworldpay_connection_url.rstrip('/')
        return {
            'provider_id': provider.id,
            'reference': link_rec.reference,
            'payment_link': f'{base_url}/neatworldpay/payment_link/{payload}',
        }

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        vals.update(self._generate_link_values())
        return vals

    @api.onchange('provider_id')
    def _onchange_provider_id(self):
        if self.provider_id:
            values = self._generate_link_values(self.provider_id.sudo())
            self.reference = values.get('reference')
            self.payment_link = values.get('payment_link')
