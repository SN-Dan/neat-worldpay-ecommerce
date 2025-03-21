/** @odoo-module */

import { _t } from '@web/core/l10n/translation';
import checkoutForm from 'payment.checkout_form';
import manageForm from 'payment.manage_form';

const neatWorldpayMixin = {
    /**
     * Prepare the provider-specific inline form of the selected payment option.
     *
     * For a provider to manage an inline form, it must override this method. When the override
     * is called, it must lookup the parameters to decide whether it is necessary to prepare its
     * inline form. Otherwise, the call must be sent back to the parent method.
     *
     * @private
     * @param {string} code - The code of the selected payment option's provider
     * @param {number} paymentOptionId - The id of the selected payment option
     * @param {string} flow - The online payment flow of the selected payment option
     * @return {Promise}
     */
    _prepareInlineForm: function (code, paymentOptionId, flow) {
        if (code !== 'neatworldpay') {
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
     * Redirect the customer to Stripe hosted payment page.
     *
     * @override method from payment.payment_form_mixin
     * @private
     * @param {string} code - The code of the payment option
     * @param {number} paymentOptionId - The id of the payment option handling the transaction
     * @param {object} processingValues - The processing values of the transaction
     * @return {undefined}
     */
    _processDirectPayment: function (code, providerId, processingValues) {
        if (code !== 'neatworldpay') {
            this._super(...arguments);
            return;
        }
        if(processingValues.neatworldpay_use_iframe) {
            this._enableButton()
            $('body').unblock();
            const popup = document.querySelector('#neatworldpay_popup');
            if (popup) popup.style.display = 'block';
            document.querySelector('#confirm_payment').addEventListener('click', (e) => {
                e.preventDefault()
                this._disableButton(true)
                popup.style.display = 'none'
                $('body').block();
                this._rpc({
                    route: '/payment/neatworldpay/process', 
                    params: {
                        'reference': processingValues.reference,
                        'result_state': 'done',
                    }
                }).then(() => {
                    window.location = '/payment/status';
                }).catch(error => {
                    this._displayErrorDialog(_t("Payment processing failed"), error.data.message);
                    this._enableButton?.(); // This method doesn't exists in Express Checkout form.
                });
            });
            document.querySelector('#close_popup').addEventListener('click', () => {
                e.preventDefault()
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

}

checkoutForm.include(neatWorldpayMixin);
manageForm.include(neatWorldpayMixin);