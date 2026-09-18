# -*- coding: utf-8 -*-
from odoo import _, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_open_worldpay_link_popup(self):
        view = self.env.ref('payment_neatworldpay.worldpay_link_popup_view_form')
        return {
            'name': _('Pay by WorldPay Link'),
            'type': 'ir.actions.act_window',
            'res_model': 'worldpay.link.popup',
            'view_mode': 'form',
            'view_id': view.id,
            'target': 'new',
        }
