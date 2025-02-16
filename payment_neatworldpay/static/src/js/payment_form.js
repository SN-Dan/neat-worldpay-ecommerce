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
        debugger
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
        debugger
        if (flow === 'token') {
            return; // No elements for tokens.
        }

        this._setPaymentFlow('direct');
    },
    // #=== PAYMENT FLOW ===#

    /**
     * Trigger the payment processing by submitting the elements.
     *
     * @override method from @payment/js/payment_form
     * @private
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option.
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {string} flow - The payment flow of the selected payment option.
     * @return {void}
     */
    async _initiatePaymentFlow(providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode !== 'neatworldpay') {
            await this._super(...arguments); // Tokens are handled by the generic flow.
            return;
        }

        // Trigger form validation and wallet collection.
        debugger
        const _super = this._super.bind(this);
        try {
            //TODO initialize worldpay flow
            console.log({
                providerCode,
                paymentOptionId,
                paymentMethodCode,
                flow
            })
        } catch (error) {
            this._displayErrorDialog(_t("Incorrect payment details"), error.message);
            this._enableButton();
            return
        }
        return await _super(...arguments);
    },

    /**
     * Process Stripe implementation of the direct payment flow.
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
            await this._super(...arguments);
            return;
        }
        debugger


        console.log({
            providerCode, paymentOptionId, paymentMethodCode, processingValues
        })
        console.log(this)
//        const { error } = await this._stripeConfirmIntent(processingValues, paymentOptionId);
//        if (error) {
//            this._displayErrorDialog(_t("Payment processing failed"), error.message);
//            this._enableButton();
//        }

        //TODO start payment
    },
});