document
    .getElementById("assistant-form")
    .addEventListener("submit", async function(event) {

        event.preventDefault();

        const input =
            document.getElementById("user-message");

        const message =
            input.value.trim();

        if (!message) {
            return;
        }

        const chatBox =
            document.getElementById("chat-box");


        // Show user's message

        const userMessage =
            document.createElement("div");

        userMessage.className = "course-item";

        userMessage.innerHTML =
            "<p><strong>You:</strong> "
            + message
            + "</p>";

        chatBox.appendChild(userMessage);


        input.value = "";


        // Send message to Flask backend

        const formData = new FormData();

        formData.append("message", message);


        try {

            const response =
                await fetch("/assistant/ask", {

                    method: "POST",

                    body: formData

                });


            const data =
                await response.json();


            // Show assistant response

            const assistantMessage =
                document.createElement("div");

            assistantMessage.className =
                "course-item";

            assistantMessage.innerHTML =
                "<p><strong>AI Assistant:</strong> "
                + data.response
                + "</p>";

            chatBox.appendChild(assistantMessage);


        } catch (error) {

            const errorMessage =
                document.createElement("div");

            errorMessage.className =
                "course-item";

            errorMessage.innerHTML =
                "<p><strong>AI Assistant:</strong> "
                + "Something went wrong. Please try again."
                + "</p>";

            chatBox.appendChild(errorMessage);

        }

    });