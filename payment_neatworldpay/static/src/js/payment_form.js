/** @odoo-module */

import { _t } from '@web/core/l10n/translation';
import paymentForm from '@payment/js/payment_form';

paymentForm.include({

     /**
     * Open the inline form of the selected payment option, if any.
     *
     * @override method from @payment/js/payment_form
     * @private
     * @param {Event} ev
     * @return {void}
     */
    async _selectPaymentOption(ev) {
        await this._super(...arguments);
    },
        /**
     * Prepare the inline form of Stripe for direct payment.
     *
     * @override method from @payment/js/payment_form
     * @private
     * @param {number} providerId - The id of the selected payment option's provider.
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {string} flow - The online payment flow of the selected payment option.
     * @return {void}
     */
    async _prepareInlineForm(providerId, providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode !== 'neatworldpay') {
            this._super(...arguments);
            return;
        }
        
        if (flow === 'token') {
            return; // No elements for tokens.
        }

        this._setPaymentFlow('direct');
    },
    
    // #=== PAYMENT FLOW ===#

    /**
     * feedback from a payment provider and redirect the customer to the status page.
     *
     * @override method from payment.payment_form
     * @private
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option.
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {object} processingValues - The processing values of the transaction.
     * @return {void}
     */
    async _processDirectFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode !== 'neatworldpay') {
            this._super(...arguments);
            return;
        }
        if(processingValues.neatworldpay_use_iframe) {
            this.call('ui', 'unblock');
            const popup = document.querySelector('#neatworldpay_popup');
            if (popup) popup.style.display = 'block';
            document.querySelector('#confirm_payment').addEventListener('click', () => {
                this.rpc('/payment/neatworldpay/process', {
                    'reference': processingValues.reference,
                    'state': 'authorized',
                }).then(() => {
                    window.location = '/payment/status';
                }).catch(error => {
                    this._displayErrorDialog(_t("Payment processing failed"), error.data.message);
                    this._enableButton?.(); // This method doesn't exists in Express Checkout form.
                });
            });
            document.querySelector('#close_popup').addEventListener('click', () => {
                location.reload();
            });
            // var customOptions = {
            //     url: processingValues.payment_url,
            //     type: 'iframe',
            //     inject: 'onload',
            //     target: 'o_neatworldpay_component_container',
            //     accessibility: true,
            //     debug: false,
            // };

            // var libraryObject = new WPCL.Library();
            // libraryObject.setup(customOptions);
        }
        else {
            window.location = processingValues.payment_url
        }
    },

});