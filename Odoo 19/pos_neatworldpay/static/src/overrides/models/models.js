/** @odoo-module */

import { register_payment_method } from "@point_of_sale/app/services/pos_store";
import { PaymentNeatWorldpay } from "@pos_neatworldpay/app/payment_neatworldpay";

register_payment_method("neatworldpay", PaymentNeatWorldpay);

