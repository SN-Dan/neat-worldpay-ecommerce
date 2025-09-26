/** @odoo-module **/

import { EpsonPrinter } from "@pos_epson_printer/app/epson_printer";
import { patch } from "@web/core/utils/patch";

patch(EpsonPrinter.prototype, {
    async sendPrintingJob(img) {
        if(window.isNeatPOSAndroidApp && window.useSelfSignedCertificates) {
            const body = await new Promise((resolve) => {
                window.selfSignedFetch(this.address, {
                    method: "POST",
                    body: img,
                    contentType: "application/xml; charset=utf-8"
                }, (result) => resolve(result));
            });
            if(body) {
                const parser = new DOMParser();
                const parsedBody = parser.parseFromString(body, "application/xml");
                const response = parsedBody.querySelector("response");
                return {
                    result: response.getAttribute("success") === "true",
                    printerErrorCode: response.getAttribute("code"),
                };
            }
            else {
                return {
                    result: false,
                    printerErrorCode: "OK",
                };
            }
        }

        return await super.sendPrintingJob(img);
    },
});