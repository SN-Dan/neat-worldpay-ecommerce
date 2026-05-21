# -*- coding: utf-8 -*-
from odoo import _, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_open_worldpay_link_popup(self):
        view = self.env.ref('payment_neatworldpay.worldpay_link_popup_view_form')
        return {
            'name': _('Pay by WorldPay Link'),
            'type': 'ir.actions.act_window',
            'res_model': 'worldpay.link.popup',
            'view_mode': 'form',
            'view_id': view.id,
            'target': 'new',
            'context': {
                **self.env.context,
                'active_model': 'sale.order',
                'active_ids': self.ids,
            },
        }
