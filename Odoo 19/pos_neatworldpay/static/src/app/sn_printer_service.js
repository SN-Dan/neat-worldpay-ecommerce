/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { PrinterService } from "@point_of_sale/app/printer/printer_service";
import { htmlToCanvas } from "@point_of_sale/app/printer/render_service";

export const snPrinterService = {
    dependencies: ["renderer"],
    start(env, { renderer }) {
        return new SNPrinterService(env, { renderer });
    },
};
export class SNPrinterService extends PrinterService {
    constructor(...args) {
        super(...args);
        this.setup(...args);
    }
    setup(env, { renderer }) {
        this.renderer = renderer;
        this.device = null;
        this.state = { isPrinting: false };
    }
    processCanvas(canvas) {
        return canvas.toDataURL("image/jpeg")
    }
    printWeb() {
        try {
            return super.printWeb(...arguments);
        } catch {
            console.error("Printing is not supported on some browsers. It is possible to print your tickets by making use of an IoT Box.")
            return false;
        }
    }
    async printHtml(el) {
        if(window.isNeatPOSAndroidApp && window.useBluetoothPrinter) {
            const image = this.processCanvas(
                await htmlToCanvas(el, { addClass: "pos-receipt-print" })
            );
            AndroidInterface.onBluetoothPrintReceipt(image)
        }
        else if(window.desktop_ws && window.is_printing_allowed_desktop_ws_map && window.is_printing_allowed_desktop_ws_map[localStorage.getItem("neatworldpay_synced_device_code")]) {
            const image = this.processCanvas(
                await htmlToCanvas(el, { addClass: "pos-receipt-print" })
            );
            window.desktop_ws.send(JSON.stringify({ type: "message", msgType: "print", msgPayload: image }));
        }
        else {
            this.setPrinter(this.hardware_proxy.printer);
            try {
                return await super.printHtml(...arguments);
            } catch (error) {
                return this.printHtmlAlternative(error, ...arguments);
            }
        }
    }
    async printHtmlAlternative(error, ...args) {
        console.error("Printing Error: using web printer instead.")
        // We want to call the _printWeb when the popup is fully gone
        // from the screen which happens after the next animation frame.
        await new Promise(requestAnimationFrame);
        return this.printWeb(...args);
    }
}

registry.category("services").remove("printer");
registry.category("services").add("printer", snPrinterService);