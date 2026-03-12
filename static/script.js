// ------------------- DOM ELEMENTS -------------------
const chatMessages     = document.querySelector(".chat-messages");
const chatInputBar     = document.querySelector(".chat-input");
const input            = document.querySelector(".message-input");
const sendBtn          = document.querySelector(".send-btn");
const chatWindow       = document.querySelector(".chat-window");

const welcomeScreen    = document.querySelector(".welcome-screen");
const welcomeForm      = document.getElementById("upload-form");
const welcomeInput     = document.querySelector(".welcome-message-input");
const welcomeFileInput = document.getElementById("welcome-file");

const fileInput        = document.getElementById("file-upload");

const newChatBtn            = document.querySelector(".new-chat-btn");
const chatHistoryContainer  = document.querySelector(".chat-history");
const sidebar               = document.querySelector(".sidebar");
const toggleBtn             = document.querySelector(".toggle-btn");

const settingsWindow        = document.getElementById("settings-window");
const settingsBtn           = document.querySelector(".mini-icon[title='Settings']");
const backToChat            = document.getElementById("back-to-chat");
const aboutWindow           = document.getElementById("about-window");
const aboutBtn              = document.querySelector(".mini-icon[title='About']");
const backToChatFromAbout   = document.getElementById("back-to-chat-from-about");

const exportBtn    = document.querySelector(".export-btn");
const exportSelect = document.getElementById("config-export");
const themeButtons = document.querySelectorAll("#config-theme .theme-option");

const filterBtn      = document.querySelector(".mini-icon[title='Filter']");
const filterSiderbar = document.getElementById("filter-sidebar");
const closeFilterBtn = document.getElementById("close-filter");
const filterContent  = document.querySelector(".filter-content");
const resizeHandle   = document.getElementById("filter-resize-handle")

//const mineSelect = document.getElementById("mine-select");
const createMineBtnWelcome = document.getElementById("create-mine-btn-welcome");
const createMineBtnChat = document.getElementById("create-mine-btn-chat")



// ------------------- STATE -------------------
let chats = {};                
let currentChatId = null;

// ============================================================================
// UI helpers
// ============================================================================
function switchToChat() {
  if (welcomeScreen && welcomeScreen.style.display !== "none") {
    welcomeScreen.style.display = "none";
    chatMessages.style.display = "flex";
    chatInputBar.style.display = "flex";
  }
}

function showTyping() {
  const el = document.createElement("div");
  el.classList.add("message", "ai", "typing");
  el.textContent = "🤖 typing...";
  chatMessages.appendChild(el);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return el;
}

function addMessage(text, sender, save = true) {
  const el = document.createElement("div");
  el.classList.add("message", sender);

  el.innerHTML = text.replace(/\n/g, "<br>"); // Preserve line breaks
  chatMessages.appendChild(el);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  if (save && currentChatId) {
    chats[currentChatId] = chats[currentChatId] || [];
    chats[currentChatId].push({ sender, text });
    updateHistoryPreview(currentChatId, text);
  }
}

function updateHistoryPreview(chatId, lastText) {
  const btn = chatHistoryContainer.querySelector(`[data-chat-id="${chatId}"]`);
  if (!btn) return;
  const preview = lastText.length > 30 ? `${lastText.slice(0,30)}…` : lastText;
  btn.textContent = `Chat ${chatId.slice(0,8)} - ${preview}`;
}

function createHistoryItem(chatId) {
  const wrapper = document.createElement("div");
  wrapper.className = "history-item-wrapper";

  const btn = document.createElement("button");
  btn.textContent = `Chat ${chatId.slice(0,8)}`;
  btn.dataset.chatId = chatId;
  btn.className = "history-item";

  btn.addEventListener("click", async () => {
    await loadChat(chatId);
    showChatInterface();
  });

  btn.addEventListener("click", async () => {
    await loadChat(chatId);
    requestAnimationFrame(showChatInterface);
  });

  const optionsBtn = document.createElement("button");
  optionsBtn.className = "history-item-options";
  optionsBtn.innerHTML = "...";

  const menu = document.createElement("div");
  menu.className = "history-item-menu";

  const delBtn = document.createElement("button");
  delBtn.textContent = "Delete Chat";

  delBtn.addEventListener("click", async () => {
    const ok = confirm("Delete this chat permanently?");
    if (!ok) return;

    await fetch(`/delete_chat?chat_id=${chatId}`, {
      method: "DELETE",
      credentials: "include"
    });

    wrapper.remove();
    if (currentChatId === chatId) {
      chatMessages.innerHTML = "";
      currentChatId = null;
    }
    menu.classList.remove("show");
  });

  menu.appendChild(delBtn);

  optionsBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.classList.toggle("show");
  });

  wrapper.appendChild(btn);
  wrapper.appendChild(optionsBtn);
  wrapper.appendChild(menu);
  return wrapper;
}

function showChatInterface()
{
  //Hide other pages
  if (settingsWindow) settingsWindow.style.display = "none";
  if (aboutWindow) aboutWindow.style.display = "none";

  //Show main chat window
  if (chatWindow) chatWindow.style.display = "flex";

  //Ensure welcome screen is hidden
  if (welcomeScreen) welcomeScreen.style.display = "none";

  //Ensure chat parts are visible
  if (chatMessages) chatMessages.style.display = "flex";
  if (chatInputBar) chatInputBar.style.display = "flex";
}

if(createMineBtnWelcome)
  {
    createMineBtnWelcome.addEventListener("click", handleCreateMine);
  }

  if(createMineBtnChat)
  {
    createMineBtnChat.addEventListener("click", handleCreateMine);
  }

// ============================================================================
// Network helpers
// ============================================================================
async function ensureChatId() {
  if (currentChatId) return currentChatId;

  const res = await fetch("/new_chat", {
    method: "POST",
    credentials: "include"
  });
  const data = await res.json();
  currentChatId = data.chat_id;

  chats[currentChatId] = [];

  const item = createHistoryItem(currentChatId);
  chatHistoryContainer.prepend(item);

  return currentChatId;
}

async function sendToAgent(userText) {
  if (!userText) return;
  switchToChat();

  await ensureChatId();

  addMessage(userText, "user");
  input.value = "";

  const typingEl = showTyping();
  try {
    const res = await fetch("/send_message", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest"
      },
      credentials: "include",
      body: JSON.stringify({
        message: userText,
        chat_id: currentChatId
      })
    });

    const data = await res.json();
    typingEl.remove();
    addMessage(data.response || "🤖 No response received.", "ai");
  } catch (err) {
    typingEl.remove();
    addMessage("❌ AI agent error.", "ai");
    console.error(err);
  }
}

async function uploadFile(files) {

  if (!currentMine)
  {
    alert("Please select or create a mine first.");
    return {ok: false}
  }

  if (!files || files.length === 0) 
    return { ok: false, response: "No file selected." };

  await ensureChatId();

  const typingEl = showTyping();

  try 
  {
    for (const file of files) 
    {
      const formData = new FormData();
      formData.append("doc_file", file);
      formData.append("chat_id", currentChatId);
      formData.append("mine_name", currentMine);

      const res = await fetch("/upload_file", {
        method: "POST",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "include",
        body: formData
      });

      const data = await res.json();

      if (!res.ok) 
      {
        addMessage(data.response || `❌ Failed to upload ${file.name}.`, "ai");
      } else 
      {
        addMessage(data.response || `✅ Uploaded: ${file.name}`, "ai");
      }
    }
    await fetch("/run_indexer", {
      method: "POST",
      credentials: "include"
    });
    typingEl.remove();

    await refreshFilterDocumentsPreserveSelection();

    return { ok: true };
  }
  catch (err) 
  {
    typingEl.remove();
    addMessage("❌ Upload failed.", "ai");

    return { ok: false};
  }  
}


// Handles combined welcome submission flow (upload → send)
async function handleWelcomeSubmit() {
  const files = Array.from(welcomeFileInput.files || []);
  const text = (welcomeInput.value || "").trim();

  switchToChat();
  await ensureChatId();

  if(files.length > 0)
  {
    for (const file of files) 
    {
      addMessage(`📎 Uploaded: ${file.name}`, "user");
    }

    await uploadFile(files);
    welcomeFileInput.value = "";
  }

  if (text) {
    await sendToAgent(text);
    welcomeInput.value = "";
  }
}

async function refreshFilterDocumentsPreserveSelection()
{
  try 
  {
    const selectedDocs = getSelectedDocuments();
    await loadFilteredDocuments(selectedDocs);

    const sidebar = document.getElementById("filter-content");
    if(sidebar)
    {
      sidebar.scrollTop = sidebar.scrollTop;
    }
  }
  catch(err)
  {
    console.error("Failed to refresh filter documents:", err);
  }
}

// ============================================================================
// Welcome screen: submit handler
// ============================================================================
welcomeForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  await handleWelcomeSubmit();
});

welcomeFileInput.addEventListener("change", async (e) => {
  const files = Array.from(e.target.files);
  if (files.length === 0) return;

  switchToChat();
  await ensureChatId();

  for (const file of files) {
    addMessage(`📎 Uploaded: ${file.name}`, "user");
  }
  await uploadFile(files);

  e.target.value = "";
});

// ============================================================================
// In-chat message sending & Enter key
// ============================================================================
sendBtn.addEventListener("click", () => {
  const text = (input.value || "").trim();
  if (!text) return;
  sendToAgent(text);
});

document.addEventListener("keydown", (e) => {
  if (e.isComposing || e.keyCode === 229) return;

  const active = document.activeElement;
  const isWelcomeBox = active && active.classList.contains("welcome-message-input");
  const isChatBox    = active && active.classList.contains("message-input");

  if (!e.shiftKey && (e.key === "Enter" || e.key === "NumpadEnter") && (isWelcomeBox || isChatBox)) {
    e.preventDefault();
    const text = (active.value || "").trim();
    if (!text) return;

    if (isWelcomeBox) handleWelcomeSubmit();
    else sendToAgent(text);
  }
});

fileInput.addEventListener("change", async (e) => {
  const files = Array.from(e.target.files);
  if (files.length === 0) return;

  switchToChat();
  await ensureChatId();

  for (const file of files) {
    addMessage(`📎 Uploaded: ${file.name}`, "user");
  }
  await uploadFile(files);
  e.target.value = "";
});

// ============================================================================
// UI controls
// ============================================================================

document.addEventListener("click", () =>{
  document.querySelectorAll(".history-item-menu").forEach(menu => menu.classList.remove("show"));
})

toggleBtn.addEventListener("click", () => {
  sidebar.classList.toggle("collapsed");
  toggleBtn.textContent = sidebar.classList.contains("collapsed") ? "➡️" : "⬅️";
});

newChatBtn.addEventListener("click", async () => {
  // Force a brand new chat from backend
  currentChatId = null;
  chatMessages.innerHTML = "";
  await ensureChatId();
  showChatInterface();
});

// Export chat to CSV (unchanged)
exportBtn.addEventListener("click", () => {
  if (!currentChatId || !chats[currentChatId]?.length) {
    alert("No messages to export.");
    return;
  }
  let csv = "data:text/csv;charset=utf-8,Question,Response\n";
  for (let i = 0; i < chats[currentChatId].length; i++) {
    if (chats[currentChatId][i].sender === "user") {
      const q = `"${chats[currentChatId][i].text.replace(/"/g, '""')}"`;
      let a = "";
      if (i + 1 < chats[currentChatId].length && chats[currentChatId][i + 1].sender === "ai") {
        a = `"${chats[currentChatId][i + 1].text.replace(/"/g, '""')}"`;
        i++;
      }
      csv += `${q},${a}\n`;
    }
  }
  const link = document.createElement("a");
  link.href = encodeURI(csv);
  link.download = `chat-${currentChatId}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
});

// Filter sidebar
filterBtn.addEventListener("click", async () => {
  filterSiderbar.style.display = "flex";
  await loadFilteredDocuments();
});

closeFilterBtn.addEventListener("click", () => {
  filterSiderbar.style.display = "none";
});

// ============================================================================
// Settings / About
// ============================================================================
settingsBtn.addEventListener("click", () => {
  chatWindow.style.display = "none";
  aboutWindow.style.display = "none";
  settingsWindow.style.display = "block";
});

backToChat.addEventListener("click", () => {
  settingsWindow.style.display = "none";
  chatWindow.style.display = "flex";
});

aboutBtn.addEventListener("click", () => {
  chatWindow.style.display = "none";
  settingsWindow.style.display = "none";
  aboutWindow.style.display = "block";
});

backToChatFromAbout.addEventListener("click", () => {
  aboutWindow.style.display = "none";
  chatWindow.style.display = "flex";
});

// ============================================================================
// Themes & Preferences 
// ============================================================================
window.addEventListener("DOMContentLoaded", () => {
  const saved = localStorage.getItem("theme") || "light";
  applyTheme(saved);

  themeButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      const t = btn.dataset.theme;
      applyTheme(t);
    });
  });

  exportSelect.value = localStorage.getItem("exportFormat") || "csv";
  exportSelect.addEventListener("change", () =>
    localStorage.setItem("exportFormat", exportSelect.value)
  );
});

function applyTheme(theme) {
  document.body.setAttribute("data-theme", theme);
  localStorage.setItem("theme", theme);
  themeButtons.forEach(btn => btn.classList.toggle("active", btn.dataset.theme === theme));
}

// ============================================================================
// Load chat list on startup + auto-load first chat
// ============================================================================
window.addEventListener("DOMContentLoaded", async () => {
  await loadMines();

  const res = await fetch("/get_chat_list", { method: "GET", credentials: "include" });
  const chatList = await res.json();

  chatHistoryContainer.innerHTML = "";
  chatList.forEach(entry => {
    const chatId = entry.chat_id;
    const item = createHistoryItem(chatId);
    chatHistoryContainer.appendChild(item);
  });

  if (chatList.length > 0) {
    await loadChat(chatList[0].chat_id);
    switchToChat();
  }
});

// ============================================================================
// Load a chat + rehydrate filters (checkboxes)
// ============================================================================
async function loadChat(chatId) {
  const res = await fetch(`/get_chat_history?chat_id=${chatId}`, {
    method: "GET",
    credentials: "include"
  });

  const data = await res.json();
  const history = data.chat_history || [];
  const activeDocs = data.active_documents || [];

  chats[chatId] = history.map(m => ({
    sender: m.role === "assistant" ? "ai" : "user",
    text: m.message
  }));

  currentChatId = chatId;
  renderChat(chatId);

  document.querySelectorAll(".history-item").forEach(b =>
    b.classList.toggle("active", b.dataset.chatId === chatId)
  );

  // If filter sidebar is open, reflect active docs immediately
  if (filterSiderbar.style.display === "flex") {
    await loadFilteredDocuments(activeDocs);
  }
}

function renderChat(chatId) {
  chatMessages.innerHTML = "";
  (chats[chatId] || []).forEach(m => {
    const el = document.createElement("div");
    el.classList.add("message", m.sender);
    el.innerHTML = m.text.replace(/\n/g, "<br>"); // Preserve line breaks
    chatMessages.appendChild(el);
  });
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

// ============================================================================
// Filters
// ============================================================================
function getSelectedDocuments() {
  return Array.from(
    document.querySelectorAll('.filter-doc-item input[type="checkbox"]:checked')
  ).map(cb => cb.value);
}

async function loadFilteredDocuments(forceChecked = [])
{
  try
  {
    const response = await fetch("/get_filterdocuments", {
      credentials: "include"
    });

    const structure = await response.json();

    filterContent.innerHTML = "";

    if(!structure || Object.keys(structure).length === 0)
      {
        filterContent.innerHTML = "<p>No documents available.</p>";
        return;
      }

      Object.entries(structure).forEach(([mine, files]) => {

        //folder container
        const folderDiv = document.createElement("div");
        folderDiv.className = "filter-folder";

        const folderLabel = document.createElement("label");
        folderLabel.className = "filter-folder-label";

        //folder checkbox
        const folderCheckbox = document.createElement("input");
        folderCheckbox.type = "checkbox";
        folderCheckbox.dataset.mine = mine;

        folderLabel.appendChild(folderCheckbox);
        folderLabel.appendChild(document.createTextNode(` ${mine}`));

        folderDiv.appendChild(folderLabel);

        //File Container
        const fileListDiv = document.createElement("div");
        fileListDiv.className = "filter-file-list";

        let validFileCount = 0;
        let checkedFileCount = 0;

        files.forEach(filename => {

          if(filename === ".init") return; //Skip .init files

          validFileCount++;

          const fullPath = `${mine}/${filename}`;

          const fileLabel = document.createElement("label");
          fileLabel.className = "filter-doc-item";

          const fileCheckbox = document.createElement("input");
          fileCheckbox.type = "checkbox";
          fileCheckbox.value = fullPath;

          if(forceChecked.includes(fullPath))
          {
            fileCheckbox.checked = true;
            checkedFileCount++;
          }

          fileLabel.appendChild(fileCheckbox);
          fileLabel.appendChild(document.createTextNode(`${filename}`));

          fileListDiv.appendChild(fileLabel);

          //Individual File Change

          fileCheckbox.addEventListener("change", async () => {
            const selectedDocs = getSelectedDocuments();

            const allFiles = fileListDiv.querySelectorAll("input[type='checkbox']");
            const checkedFiles = fileListDiv.querySelectorAll("input[type='checkbox']:checked");

            folderCheckbox.checked = allFiles.length > 0 && allFiles.length === checkedFiles.length;

            await fetch("/set_active_documents", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest"
              },
              credentials: "include",
              body: JSON.stringify({
                chat_id: currentChatId,
                documents: selectedDocs
              })
            });
          });
        });

        folderCheckbox.checked = validFileCount > 0 && checkedFileCount === validFileCount;

        //Folder checkbox behaviour

        folderCheckbox.addEventListener("change", async () => {
          const checkboxes = fileListDiv.querySelectorAll("input[type='checkbox']")

          checkboxes.forEach(cb => {
            cb.checked = folderCheckbox.checked;
          });

          const selectedDocs = getSelectedDocuments();

          await fetch("/set_active_documents", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Requested-With": "XMLHttpRequest"
            },
            credentials: "include",
            body: JSON.stringify({
              chat_id: currentChatId,
              documents: selectedDocs
            })
          });
        });

        folderDiv.appendChild(fileListDiv);
        filterContent.appendChild(folderDiv);
      });
  }
  catch(err){
    console.error("Error loadinf documents.", err);
    filterContent.innerHTML = "<p>Error loading documents.</p>"
  }
}

async function loadMines()
{
 try
 {
  const res = await fetch("/get_mines", {
    credentials: "include"
  });

  const mines = await res.json();

  const welcomeSelect = document.getElementById("welcome-mine-select");
  const chatSelect = document.getElementById("chat-mine-select");

  if(welcomeSelect)
  {
    welcomeSelect.innerHTML = '<option value="">Select Mine</option>';
  }
  if(chatSelect)
  {
    chatSelect.innerHTML = '<option>Select Mine</option>';
  }

  mines.forEach(mine => {
    const opt1 = document.createElement("option")
    opt1.value = mine;
    opt1.textContent = mine;

    const opt2 = opt1.cloneNode(true);

    if(welcomeSelect) welcomeSelect.appendChild(opt1);
    if(chatSelect) chatSelect.appendChild(opt2);
  });
 }
 catch(err)
 {
  console.error("Error loading mines:", err)
 }
}

let currentMine = null;

const welcomeMineSelect = document.getElementById("welcome-mine-select");
const chatMineSelect = document.getElementById("chat-mine-select");

if(welcomeMineSelect)
{
  welcomeMineSelect.addEventListener("change", () =>{
    currentMine = welcomeMineSelect.value;
    if(chatMineSelect) chatMineSelect.value = currentMine;
    console.log("Selected mine:", currentMine);
  });
}

if(chatMineSelect)
{
  chatMineSelect.addEventListener("change", () =>{
    currentMine = chatMineSelect.value;
    if(welcomeMineSelect) welcomeMineSelect.value = currentMine;
    console.log("Selected mine:", currentMine);
  });
}

async function handleCreateMine() {
  const mineName = prompt("Enter new mine name:");
  if(!mineName) return;

  try
  {
    const res = await fetch("/create_mine", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest"
      },
      credentials: "include",
      body: JSON.stringify({mine_name: mineName})
    });

    const data = await res.json();

    if (res.ok)
      {
        alert("Mine created successfully.");
        await loadMines();
      }
      else
      {
        alert(data.error || "Failed to create mine.")
      }
  }
  catch (err)
  {
    console.error("Create mine failed:", err);
  }
};

if(resizeHandle && filterSiderbar)
{
  let isResizing = false;

  resizeHandle.addEventListener("mousedown", (e) => {
    isResizing = true;
    document.body.style.cursor = "ew-resize";
  });

  document.addEventListener("mousemove", (e) => {
    if (!isResizing) return;
    const newWidth = e.clientX - filterSiderbar.getBoundingClientRect().left;

    if (newWidth >= 260 && newWidth <= 600) 
      {
        filterSiderbar.style.width = newWidth + "px";
      }
  });

  document.addEventListener("mouseup", () => {
    isResizing = false;
    document.body.style.cursor = "default";
  });

}
