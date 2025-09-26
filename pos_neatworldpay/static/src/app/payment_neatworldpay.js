/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { PaymentInterface } from "@point_of_sale/app/utils/payment/payment_interface";

export class PaymentNeatWorldpay extends PaymentInterface {
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
    addCss() {
        const customModalStyles = `
            .neat-worldpay-modal-text {
                width: 380px;
                text-align: center;
            }
            .neat-worldpay-modal {
                display: inline-block;
                position: fixed;
                z-index: 1000;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                background-color: rgba(0, 0, 0, 0.5);
            }

            .neat-worldpay-modal-content {
                background-color: #fff;
                border-radius: 5px;
                position: absolute;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                padding: 20px;
                max-width: 400px;
            }

            /* Button styles */
            .neat-worldpay-modal-button {
                width: calc(100% - 20px);
                height: 55px;
                margin: 5px;
                cursor: pointer;
                font-size: 25px;
                border: none;
                background: darkseagreen;
                color: white;
            }
            .neat-worldpay-modal-input {
                width: calc(100% - 20px);
                height: 45px;
                margin: 5px;
                padding: 10px;
                font-size: 20px;
                border: 1px solid #ccc;
                border-radius: 4px;
                box-sizing: border-box;
            }
        `;

        // Create a <style> element and append it to the document's <head>
        const styleElement = document.createElement('style');
        styleElement.innerHTML = customModalStyles;
        document.head.appendChild(styleElement);
    }
    displaySyncModal() {
        if (document.querySelector('.neat-worldpay-modal')) {
            return; // Modal already exists, do nothing
        }
        const modal = document.createElement('div');
        modal.classList.add('neat-worldpay-modal');
        modal.innerHTML = `
            <div class="neat-worldpay-modal-content">
                <h2 class="neat-worldpay-modal-text">Enter the terminal device code to sync.</h2>
                <div>
                    <input type="text" id="deviceCodeInput" placeholder="Device Code"
                        class="neat-worldpay-modal-input" />
                    <button class="neat-worldpay-modal-button" id="btnSync">Sync</button>
                </div>
            </div>
        `;

        // Add the modal to the document body
        document.body.appendChild(modal);

        // Function to close the modal
        function closeModal() {
            document.body.removeChild(modal);
        }
        var btn = document.getElementById("btnSync")
        // Event listeners for button clicks
        btn.addEventListener("click", function(e) {
            const deviceCode = document.getElementById('deviceCodeInput').value;
            localStorage.setItem('neatworldpay_synced_device_code', deviceCode)
            closeModal();
            window.socket_connect(true)
        });
    }
    socket_connect(initialConnect = false) {
        if(!window.desktop_ws || !initialConnect) {
            window.desktop_ws = new WebSocket(window.desktop_ws_url)
            window.desktop_ws.onopen = () => {
                const syncedDeviceCode = localStorage.getItem("neatworldpay_synced_device_code")
                window.desktop_ws.send(JSON.stringify({ type: "register", deviceId: syncedDeviceCode + "-pc" }));
                console.log("Connected and registered.");
            }
            window.desktop_ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                if(msg.msgType === 'barcode') {
                    const barcodeInput = document.querySelector('body .o-barcode-input');
                    console.log(barcodeInput);

                    for (let i = 0; i < msg.msgPayload.length; i++) {
                        const char = msg.msgPayload.charAt(i);
                        const event = new KeyboardEvent('keydown', {
                            key: char,
                            bubbles: true,
                            cancelable: true
                        });
                        console.log(char);
                        document.body.dispatchEvent(event);
                    }
                }
                window.desktop_ws.send(JSON.stringify({ type: "ack", msgId: msg.msgId }));
            }
            window.desktop_ws.onerror = () => {
                window.desktop_ws.close()
                console.log("Disconnected, retrying...");
            }
            window.desktop_ws.onclose = () => {
                console.log("Disconnected, retrying...");
                setTimeout(window.socket_connect, 1000);
            }
        }
    }
    /**
     * @override
    */
    setup() {
        super.setup(...arguments);
        window.is_printing_allowed_desktop_ws_map = {}
        this.addCss()
        const device = window.navigator.userAgent
        const isMobile = device.includes("Android") || window.isNeatPOSAndroidApp
        var pm = this.payment_method
        if(!pm) {
            pm = this.payment_method_id
        }
        if(pm && pm.neat_worldpay_is_desktop_mode && pm.neat_worldpay_is_local_ws_server && !isMobile){
            window.is_printing_allowed_desktop_ws_map[pm.neat_worldpay_terminal_device_code] = pm.neat_worldpay_is_terminal_printer_communication_allowed
            if(pm.neat_worldpay_ws_url) {
                window.socket_connect = this.socket_connect.bind(this)
                window.desktop_ws_url = pm.neat_worldpay_ws_url
                if(localStorage.getItem("neatworldpay_synced_device_code")) {
                    this.socket_connect(true)
                }
                else {
                    this.displaySyncModal()
                }
            }
        }
    }
    /**
     * @override
    */
    async sendPaymentRequest (cid) {
        try {
            super.sendPaymentRequest(...arguments);
            const line = this._get_payment_line();
            const order = this.pos.getOrder();
            const data = this._terminal_pay_data();
            const terminalId = data.PaymentMethod.neat_worldpay_terminal_device_code
            const refunded_order_line_ids = []

            for(let i = 0; i < order.lines.length; i++) {
                var orderline = order.lines[i]
                if(orderline.refunded_orderline_id) {
                    refunded_order_line_ids.push(orderline.refunded_orderline_id.id)
                }
            }

            if(refunded_order_line_ids.length > 1) {
                try {
                    const iosr = await this.env.services.orm.rpc('/pos_worldpay/is_order_the_same', {
                            refunded_order_line_ids
                    })

                    if(!iosr || !iosr.data || !iosr.data.is_order_the_same) {
                        line.set_payment_status('retry');
                        throw new Error('Cannot have multiple refunds in an order.');
                        return
                    }
                }
                catch(e) {
                    line.set_payment_status('retry');
                    throw new Error('Cannot have multiple refunds in an order.');
                    return
                }
            }

            var refunded_order_line_id = undefined
            if(refunded_order_line_ids.length) {
                refunded_order_line_id = refunded_order_line_ids[0]
            }

            const params = {
                terminal_id: terminalId,
                order_id: data.OrderID,
                amount: data.RequestedAmount,
                user_id: order.user_id.id,
                refunded_order_line_id,
            }
            const result = await this.env.services.orm.rpc('/pos_worldpay/create_payment_request', params)
            if(!result || result.status === 403 || result.status === 400) {
                line.set_payment_status('retry');
                return false
            }
            const device = window.navigator.userAgent
            const isMobile = device.includes("Android") || window.isNeatPOSiOSApp
            if(result && result.status === 201 && data.PaymentMethod.neat_worldpay_is_mobile && isMobile) {
                if(window.isNeatPOSAndroidApp) {
                    AndroidInterface.onPayment("btnPayPal")
                }
                else {
                    var currentURL = window.location.href;
                    var encodedURL = encodeURIComponent(currentURL);
                    window.open("app://neat-worldpay-payment-android?paymentType=0&redirectUrl=" + encodedURL);
                }
            }
            else if(result && result.status === 201 && data.PaymentMethod.neat_worldpay_is_desktop_mode && data.PaymentMethod.neat_worldpay_is_local_ws_server && data.PaymentMethod.neat_worldpay_ws_url && !isMobile && data.PaymentMethod.neat_worldpay_terminal_device_code === localStorage.getItem("neatworldpay_synced_device_code")) {
                window.desktop_ws.send(JSON.stringify({ type: "message", msgType: "payment" }));
            }
            line.set_payment_status('waitingCard');
            while(true) {
                try {
                    const res = await this.env.services.orm.rpc('/pos_worldpay/check_request', {
                        terminal_id: terminalId,
                        transaction_id: result.data.transaction_id,
                    })

                    if(res && res.status === 200) {
                        if(res.data.status === 'done' || res.data.status === 'refunded' || res.data.status === 'resent_done' || res.data.status === 'resent_refunded') {
                            const processed_result = await this.env.services.orm.rpc('/pos_worldpay/request_processed', {
                                terminal_id: terminalId,
                                transaction_id: res.data.transaction_id,
                            })
                            if(processed_result && processed_result.status == 200) {
                                try {
                                    line.transaction_id = res.data.transaction_id;
                                    line.card_type = res.data.card_type;
                                    line.cardholder_name = res.data.cardholder_name
                                    if(res.data.is_refund && line.amount !== res.data.refunded_amount) {
                                        if(res.data.refunded_amount < 0) {
                                            line.amount = res.data.refunded_amount
                                        }
                                        else {
                                            line.amount = -1 * res.data.refunded_amount
                                        }
                                    }
                                    else {
                                        line.amount = res.data.transaction_amount
                                    }
                                    line.set_payment_status('done');
                                    return true
                                }
                                catch(e) {
                                    console.log(e)
                                    await this.env.services.orm.rpc('/pos_worldpay/log_message_ui', {
                                        terminal_id: terminalId,
                                        transaction_id: res.data.transaction_id,
                                        type: 'error',
                                        message: 'Error setting payment status: ' + e.message
                                    })
                                    return false
                                }
                            }
                        }
                        else if(res.data.status !== 'pending') {
                            line.set_payment_status('retry');
                            return false
                        }
                    }
                    else {
                        line.set_payment_status('retry');
                        return false
                    }
                }
                catch(e) {

                }
                await this.sleep(2000)
            }
            return true
        }
        catch(e) {
            const line = this._get_payment_line();
            line.set_payment_status('retry');
            return false
        }
    }
    /**
     * @override
    */
    async sendPaymentCancel(order, uuid) {
        try {
            super.sendPaymentCancel(...arguments);
            console.log('cancel')
            const line = this._get_payment_line();
            const data = this._terminal_pay_data();
            const terminalId = data.PaymentMethod.neat_worldpay_terminal_device_code
            const res = await this.env.services.orm.rpc('/pos_worldpay/cancel_payment_request', {
                terminal_id: terminalId,
                order_id: data.OrderID,
            })
        }
        catch(e) {
            //this.displayMessage(this, "Error", "Connection with server lost. Please wait while the server reconnects and try again.", "Ok", "btnOkCancel");
        }
        return true;
    }
    _get_payment_line() {
        var line = this.pos.getOrder().getSelectedPaymentline()
        return line
    }
    _terminal_pay_data() {
          const order = this.pos.getOrder();
          const line = this._get_payment_line();
          var orderId = order.uid
          if(!orderId) {
            orderId = order.pos_reference
          }
          var pm = this.payment_method
          if(!pm) {
            pm = this.payment_method_id
          }
          const data = {
                'Name': order.name,
                'OrderID': orderId,
                'Currency': this.pos.currency.name,
                'RequestedAmount': line.amount,
                'PaymentMethod': pm
          };
         return data;
    }
}


