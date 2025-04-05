function showActivationForm(e) {
    e.preventDefault()
    const formPopup = document.querySelector("#neatworldpay_form");
    formPopup.style.display = "block";
    const closeButton = document.querySelector(".neatworldpay_close_form");
    const form = formPopup.children[1]
    const submitButton = formPopup.children[2]

    if (!window.isFormActivated) {
        // Close form when "Cancel" is clicked
        closeButton.addEventListener("click", function (e) {
            e.preventDefault()
            formPopup.style.display = "none";
        });

        // Create and append form fields dynamically if they don't exist
        function createFormFields() {
            // Check if each field exists, if not create it
            const fieldsData = [
                { id: 'neatworldpay_email', label: 'Email', type: 'email' },
                { id: 'neatworldpay_name', label: 'Name', type: 'text' },
                { id: 'neatworldpay_company', label: 'Company', type: 'text' },
                { id: 'neatworldpay_phone', label: 'Phone Number', type: 'text' },
            ];

            fieldsData.forEach(field => {
                if (!document.querySelector(`#${field.id}`)) {
                    // Create label element
                    const label = document.createElement('label');
                    label.setAttribute('for', field.id);
                    label.textContent = field.label;

                    // Create input element
                    const input = document.createElement('input');
                    input.setAttribute('type', field.type);
                    input.setAttribute('id', field.id);
                    input.setAttribute('name', field.id);
                    input.setAttribute('placeholder', `Enter your ${field.label.toLowerCase()}`);
                    input.setAttribute('required', 'true');

                    // Append label and input to the form
                    form.appendChild(label);
                    form.appendChild(input);
                }
            });
        }

        // Call the function to create the form fields dynamically
        createFormFields();

        function isValidEmail(email) {
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            return emailRegex.test(email);
        }

        submitButton.addEventListener("click", function (event) {
            event.preventDefault(); // Prevent page reload

            const email = document.querySelector("#neatworldpay_email");
            const company = document.querySelector("#neatworldpay_company");
            const phone = document.querySelector("#neatworldpay_phone");
            const name = document.querySelector("#neatworldpay_name");

            if (!email.value || !isValidEmail(email.value) || !company.value || !phone.value || !name.value) {
                alert("Please fill in all fields.");
                return;
            }
            submitButton.textContent = "Sending..."

            fetch("https://xgxl6uegelrr4377rvggcakjvi0djbts.lambda-url.eu-central-1.on.aws/api/AcquirerLicense/contact", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ email: email.value, company: company.value, phone: phone.value, name: name.value }),
            })
            .then(response => {
                submitButton.textContent = "Submit"
                if (response.ok) {
                    alert("Activation code request sent. We will be in touch shortly.");
                    formPopup.style.display = "none";
                    email.value = ""
                    company.value = ""
                    phone.value = ""
                    name.value = ""
                } else {
                    throw new Error("Failed to send request.");
                }
            })
            .catch(error => {
                console.error("Error:", error);
                alert("Failed to send contact request please try again.");
            });
        });
        window.isFormActivated = true
    }
}