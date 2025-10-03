// script.js

const input = document.querySelector(".message-input");
const sendBtn = document.querySelector(".send-btn");
const chatMessages = document.querySelector(".chat-messages");
const fileInput = document.querySelector("#file-upload");
const newChatBtn = document.querySelector(".new-chat");
const chatHistoryContainer = document.querySelector(".chat-history");

const welcomeInput = document.querySelector(".welcome-message-input");
const welcomeSendBtn = document.querySelector(".welcome-send-btn");
const welcomeScreen = document.querySelector(".welcome-screen");

const normalMessages = document.querySelector(".chat-messages");
const normalInput = document.querySelector(".chat-input");

const sidebar = document.querySelector(".sidebar");
const toggleBtn = document.querySelector(".toggle-btn");
const exportBtn = document.querySelector(".export-btn");

const chatWindow = document.querySelector(".chat-window");
const settingsWindow = document.getElementById("settings-window");
const settingsBtn = document.querySelector(".mini-icon[title='Settings']");
const backToChat = document.getElementById("back-to-chat");

const exportSelect = document.getElementById("config-export");
const themeSelect = document.getElementById("config-theme");


// State
let chats = {};          // { chatId: [ { sender, text } ] }
let currentChatId = null;
let chatCounter = 0;

// Create a history button for a chat
function createHistoryButton(chatId, title) {
  const btn = document.createElement("button");
  btn.className = "history-item";
  btn.textContent = title;
  btn.dataset.chatId = chatId;
  btn.addEventListener("click", () => setActiveChat(chatId));
  chatHistoryContainer.appendChild(btn);
  return btn;
}

// Set a chat as active and render it
function setActiveChat(chatId) {
  if (!chats[chatId]) return;
  currentChatId = chatId;

  // update active class on sidebar buttons
  document.querySelectorAll(".chat-history .history-item").forEach(b => {
    b.classList.toggle("active", b.dataset.chatId === chatId);
  });

  renderChat(chatId);
}

// Create a new chat session and select it
function createChat() {
  chatCounter++;
  const id = `chat-${chatCounter}`;
  chats[id] = [];
  createHistoryButton(id, `Chat ${chatCounter}`);
  setActiveChat(id);
  return id;
}

// Render messages for a chat
function renderChat(chatId) {
  chatMessages.innerHTML = "";
  const msgs = chats[chatId] || [];
  msgs.forEach(m => {
    const el = document.createElement("div");
    el.classList.add("message", m.sender);
    el.textContent = m.text;
    chatMessages.appendChild(el);
  });
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Add a message to the UI (and save to the current chat if save=true)
function addMessage(text, sender, save = true) {
  const el = document.createElement("div");
  el.classList.add("message", sender);
  el.textContent = text;
  chatMessages.appendChild(el);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  if (save) {
    // ensure there's an active chat
    if (!currentChatId) createChat();
    chats[currentChatId].push({ sender, text });
    updateHistoryPreview(currentChatId, text);
  }
}

// Update the history button text to show a short preview of the last message
function updateHistoryPreview(chatId, lastText) {
  const btn = chatHistoryContainer.querySelector(`[data-chat-id="${chatId}"]`);
  if (!btn) return;
  const base = btn.textContent.split(" — ")[0]; // "Chat N"
  const short = lastText.length > 30 ? lastText.slice(0, 30) + "…" : lastText;
  btn.textContent = `${base} — ${short}`;
}

// Typing indicator
function showTypingIndicator() {
  const typingEl = document.createElement("div");
  typingEl.classList.add("message", "ai", "typing");
  typingEl.textContent = "🤖 typing...";
  chatMessages.appendChild(typingEl);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return typingEl;
}

// ---- Welcome screen -> normal chat switch ----
function switchToChat() {
  welcomeScreen.style.display = "none";
  normalMessages.style.display = "flex";
  normalInput.style.display = "flex";
}

// Handle welcome send
welcomeSendBtn.addEventListener("click", () => {
  const text = welcomeInput.value.trim();
  if (text === "") return;

  switchToChat();

  // Create first chat if needed
  if (!currentChatId) createChat();

  addMessage(text, "user", true);
  welcomeInput.value = "";

  // Simulated AI response
  const typingEl = showTypingIndicator();
  setTimeout(() => {
    typingEl.remove();
    addMessage("🤖 This is a response from the AI agent.", "ai", true);
  }, 1200);
});

// Enter key to send in welcome input
welcomeInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    welcomeSendBtn.click();
  }
});

// ---- Normal chat handlers ----

// Send button handler
sendBtn.addEventListener("click", () => {
  const userText = input.value.trim();
  if (userText === "") return;

  // If no active chat, create one automatically
  if (!currentChatId) createChat();

  addMessage(userText, "user", true);
  input.value = "";

  // Simulated AI response
  const typingEl = showTypingIndicator();
  setTimeout(() => {
    typingEl.remove();
    addMessage("🤖 This is a response from the AI agent.", "ai", true);
  }, 1200);
});

// Enter key to send in normal input
input.addEventListener("keypress", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    sendBtn.click();
  }
});

// File upload handling
fileInput.addEventListener("change", () => {
  if (fileInput.files.length === 0) return;
  const name = fileInput.files[0].name;
  if (!currentChatId) createChat();
  addMessage(`📎 Uploaded: ${name}`, "user", true);
});

toggleBtn.addEventListener("click", () => {
  sidebar.classList.toggle("collapsed");

  // Flip arrow direction
  toggleBtn.textContent = sidebar.classList.contains("collapsed") ? "➡️" : "⬅️";
});

// New chat button
newChatBtn.addEventListener("click", () => {
  createChat();
});

exportBtn.addEventListener("click", () => {
  if (!currentChatId || !chats[currentChatId] || chats[currentChatId].length === 0) {
    alert("No messages to export.");
    return;
  }

  // CSV header
  let csvContent = "data:text/csv;charset=utf-8,Question,Response\n";

  // Iterate through chat messages and pair user/ai
  for (let i = 0; i < chats[currentChatId].length; i++) {
    if (chats[currentChatId][i].sender === "user") {
      const question = `"${chats[currentChatId][i].text.replace(/"/g, '""')}"`;
      let response = "";

      // check if next message is AI response
      if (i + 1 < chats[currentChatId].length && chats[currentChatId][i + 1].sender === "ai") {
        response = `"${chats[currentChatId][i + 1].text.replace(/"/g, '""')}"`;
        i++; // skip the AI response since we already paired it
      }

      csvContent += `${question},${response}\n`;
    }
  }

  // Trigger download
  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", `chat-${currentChatId}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
});

settingsBtn.addEventListener("click", () => {
  chatWindow.style.display = "none";       // hide chat
  settingsWindow.style.display = "block";   // show settings
});

backToChat.addEventListener("click", () => {
  settingsWindow.style.display = "none";   // hide settings
  chatWindow.style.display = "flex";       // show chat again
});

// Load saved settings
exportSelect.value = localStorage.getItem("exportFormat") || "csv";
themeSelect.value = localStorage.getItem("theme") || "light";

// Save on change
exportSelect.addEventListener("change", () => {
  localStorage.setItem("exportFormat", exportSelect.value);
});

themeSelect.addEventListener("change", () => {
  localStorage.setItem("theme", themeSelect.value);
  document.body.setAttribute("data-theme", themeSelect.value); // apply theme
});

//About js

const aboutWindow = document.getElementById("about-window");
const aboutBtn = document.querySelector(".mini-icon[title='About']");
const backToChatFromAbout = document.getElementById("back-to-chat-from-about");

// Show Settings (and hide About)
settingsBtn.addEventListener("click", () => {
  chatWindow.style.display = "none";
  aboutWindow.style.display = "none";     // hide about
  settingsWindow.style.display = "block"; // show settings
});

// Back from Settings
backToChat.addEventListener("click", () => {
  settingsWindow.style.display = "none";
  chatWindow.style.display = "flex";
});

// Show About (and hide Settings)
aboutBtn.addEventListener("click", () => {
  chatWindow.style.display = "none";
  settingsWindow.style.display = "none";  // hide settings
  aboutWindow.style.display = "block";    // show about
});

// Back from About
backToChatFromAbout.addEventListener("click", () => {
  aboutWindow.style.display = "none";
  chatWindow.style.display = "flex";
});

