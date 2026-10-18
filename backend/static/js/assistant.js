
document
    .getElementById("assistant-form")
    .addEventListener("submit", async function (event) {
        event.preventDefault();

        const input = document.getElementById("user-message");
        const chatBox = document.getElementById("chat-box");
        const message = input.value.trim();

        if (!message) return;

        // Create a message safely without inserting user text as HTML.
        function addMessage(text, sender) {
            const row = document.createElement("div");
            row.className = `chat-message ${sender}-message`;

            if (sender === "assistant") {
                const avatar = document.createElement("div");
                avatar.className = "chat-avatar";
                avatar.textContent = "🤖";
                avatar.setAttribute("aria-hidden", "true");
                row.appendChild(avatar);
            }

            const bubble = document.createElement("div");
            bubble.className = "chat-bubble";
            bubble.textContent = text;
            row.appendChild(bubble);

            chatBox.appendChild(row);
            chatBox.scrollTop = chatBox.scrollHeight;
        }


        function showTypingIndicator() {
            const row = document.createElement("div");
            row.className = "chat-message assistant-message";
            row.id = "typing-indicator";

            const avatar = document.createElement("div");
            avatar.className = "chat-avatar";
            avatar.textContent = "🤖";

            const bubble = document.createElement("div");
            bubble.className = "typing-bubble";
            bubble.innerHTML = "<span></span><span></span><span></span>";

            row.appendChild(avatar);
            row.appendChild(bubble);
            chatBox.appendChild(row);
            chatBox.scrollTop = chatBox.scrollHeight;
        }

        addMessage(message, "user");
        showTypingIndicator();
        input.value = "";
        input.focus();

        const sendButton = event.submitter;
        if (sendButton) sendButton.disabled = true;

        try {
            const formData = new FormData();
            formData.append("message", message);

            const response = await fetch("/assistant/ask", {
                method: "POST",
                body: formData
            });

            const data = await response.json();
            document.getElementById("typing-indicator")?.remove();

            if (!response.ok) {
                addMessage(
                    data.response || "Sorry, something went wrong. Please try again.",
                    "assistant"
                );
                return;
            }

            addMessage(
                data.response || "I couldn't generate a response. Please try again.",
                "assistant"
            );
        } catch (error) {
            document.getElementById("typing-indicator")?.remove();
            addMessage(
                "Something went wrong. Please check your connection and try again.",
                "assistant"
            );
        } finally {
            if (sendButton) sendButton.disabled = false;
        }
    });
