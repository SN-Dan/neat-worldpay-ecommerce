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
            return;
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
        if(!processingValues.payment_url) {
            alert("Worldpay integration is not active. Please update the activation code.");
        }
        if(processingValues.neatworldpay_use_iframe) {
            this.call('ui', 'unblock');
            const popup = document.querySelector('#neatworldpay_popup');
            if (popup) popup.style.display = 'block';
            var customOptions = {
                url: processingValues.payment_url,
                type: 'iframe',
                inject: 'immediate',
                target: 'neatworldpay-container',
                accessibility: true,
                debug: false,
                resultCallback: (responseData) => {
                    var status = responseData.order.status
                    if(status === 'cancelled_by_shopper') {
                        location.reload();
                    }
                }
            };

            var libraryObject = new WPCL.Library();
            libraryObject.setup(customOptions);
        }
        else {
            window.top.location.href = processingValues.payment_url
        }
    },

});