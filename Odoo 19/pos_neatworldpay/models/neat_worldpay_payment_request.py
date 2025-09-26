# -*- coding: utf-8 -*-
# Original Author: Daniel Stoynev
# Copyright (c) 2025 SNS Software Ltd. All rights reserved.
# This module extends Odoo's payment framework.
# Odoo is a trademark of Odoo S.A.
import logging
import uuid
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

class NeatWorldpayPaymentRequest(models.Model):
    _name = 'neat.worldpay.payment.request'
    _description = 'NEAT Worldpay Payment Request'

    terminal_id = fields.Text('Terminal Id', required=True, readonly=False, store=True)
    order_id = fields.Text('Order Id', required=True, readonly=False, store=True)
    user_id = fields.Integer('User Id', required=True, readonly=False, store=True)
    refunded_order_line_id = fields.Integer('Refunded Order Line Id', required=False, readonly=False, store=True)
    start_date = fields.Datetime('Start Date', required=True, readonly=False, store=True)
    amount = fields.Integer('Amount', required=True, readonly=False, store=True, digits=(19, 0))
    refunded_amt = fields.Integer('Refunded', required=True, readonly=False, store=True, digits=(19, 0))
    uncommited_refunded_amt = fields.Integer('Uncommited Refunded', required=True, readonly=False, store=True, digits=(19, 0))
    status = fields.Text('Status', required=True, readonly=False, store=True)
    transaction_id = fields.Text('Transaction Id', required=True, readonly=False, store=True)
    card_type = fields.Text('Card Type', required=False, readonly=False, store=True)
    cardholder_name = fields.Text('Cardholder Name', required=False, readonly=False, store=True)
    uti = fields.Text('UTI', required=False, readonly=False, store=True)
    rrn = fields.Text('RRN', required=False, readonly=False, store=True)


