/**
 * AuraCode — Frontend Application
 * ================================
 * Handles: file tree, code editor, agent chat with SSE streaming,
 * diff rendering, model selection, and continuous session support.
 */

// ─── State ──────────────────────────────────────────────────

const state = {
    projectPath: "",
    currentFile: null,    // { path, content, language }
    isRunning: false,
    modified: false,
};

// ─── DOM References ─────────────────────────────────────────

const $fileTree     = document.getElementById("file-tree");
const $editorFile   = document.getElementById("editor-filename");
const $codeEditor   = document.getElementById("code-editor");
const $lineNumbers  = document.getElementById("line-numbers");
const $chatLog      = document.getElementById("chat-log");
const $chatInput    = document.getElementById("chat-input");
const $btnSend      = document.getElementById("btn-send");
const $btnSave      = document.getElementById("btn-save");
const $btnOpen      = document.getElementById("btn-open-project");
const $pathInput    = document.getElementById("project-path-input");
const $modelSelect  = document.getElementById("model-select");
const $statusDot    = document.getElementById("status-dot");


// ─── Initialization ─────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    checkStatus();
    loadModels();
    setupEventListeners();
    updateLineNumbers();
});


// ─── Event Listeners ────────────────────────────────────────

function setupEventListeners() {
    $btnOpen.addEventListener("click", openProject);
    $btnSend.addEventListener("click", sendTask);
    $btnSave.addEventListener("click", saveFile);
    $modelSelect.addEventListener("change", changeModel);

    $pathInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            openProject();
        }
    });

    $chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendTask();
        }
    });

    $codeEditor.addEventListener("input", () => {
        state.modified = true;
        $btnSave.disabled = false;
        updateLineNumbers();
    });

    $codeEditor.addEventListener("scroll", syncScroll);

    // Ctrl+S to save
    document.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "s") {
            e.preventDefault();
            if (state.currentFile && state.modified) {
                saveFile();
            }
        }
    });

    // Tab support in editor
    $codeEditor.addEventListener("keydown", (e) => {
        if (e.key === "Tab") {
            e.preventDefault();
            const start = $codeEditor.selectionStart;
            const end = $codeEditor.selectionEnd;
            $codeEditor.value = $codeEditor.value.substring(0, start) + "    " + $codeEditor.value.substring(end);
            $codeEditor.selectionStart = $codeEditor.selectionEnd = start + 4;
            state.modified = true;
            $btnSave.disabled = false;
            updateLineNumbers();
        }
    });

    // Resize handles
    setupResize("resize-left", "panel-files", "left");
    setupResize("resize-right", "panel-chat", "right");
}


// ─── Status & Models ────────────────────────────────────────

async function checkStatus() {
    try {
        const resp = await fetch("/api/status");
        const data = await resp.json();
        $statusDot.className = data.ollama_available ? "dot-online" : "dot-offline";
        $statusDot.title = data.ollama_available ? `Connected: ${data.model}` : "Ollama offline";
    } catch {
        $statusDot.className = "dot-offline";
    }
}

async function loadModels() {
    try {
        const resp = await fetch("/api/models");
        const data = await resp.json();
        $modelSelect.innerHTML = "";

        if (data.models && data.models.length > 0) {
            data.models.forEach(m => {
                const opt = document.createElement("option");
                opt.value = m;
                opt.textContent = m;
                if (m === data.current || m.startsWith(data.current + ":")) {
                    opt.selected = true;
                }
                $modelSelect.appendChild(opt);
            });
        } else {
            const opt = document.createElement("option");
            opt.value = "codellama";
            opt.textContent = "codellama";
            $modelSelect.appendChild(opt);
        }
    } catch {
        // keep default
    }
}

async function changeModel() {
    const model = $modelSelect.value;
    try {
        await fetch("/api/set_model", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model }),
        });
        appendChat("status", `Model changed to: ${model}`);
        checkStatus();
    } catch (e) {
        appendChat("error", `Failed to change model: ${e.message}`);
    }
}


// ─── Project / File Tree ────────────────────────────────────

function openProject() {
    const path = $pathInput.value.trim();
    if (!path) {
        appendChat("error", "Enter a project path first.");
        $pathInput.focus();
        return;
    }
    state.projectPath = path;
    loadFileTree(path);
}

async function loadFileTree(path) {
    try {
        const resp = await fetch(`/api/file_tree?path=${encodeURIComponent(path)}`);
        const data = await resp.json();

        if (data.error) {
            appendChat("error", data.error);
            return;
        }

        $fileTree.innerHTML = "";
        renderTree(data.tree, $fileTree, 0);
    } catch (e) {
        appendChat("error", `Failed to load file tree: ${e.message}`);
    }
}

function renderTree(items, parent, depth) {
    items.forEach(item => {
        const el = document.createElement("div");
        el.className = "tree-item";
        el.style.paddingLeft = `${8 + depth * 16}px`;

        if (item.type === "directory") {
            const iconSpan = document.createElement("span");
            iconSpan.className = "icon";
            iconSpan.textContent = "▶";
            el.appendChild(iconSpan);

            const nameSpan = document.createElement("span");
            nameSpan.textContent = item.name;
            el.appendChild(nameSpan);

            parent.appendChild(el);

            const childContainer = document.createElement("div");
            childContainer.className = "tree-dir-children";
            parent.appendChild(childContainer);

            renderTree(item.children || [], childContainer, depth + 1);

            el.addEventListener("click", (e) => {
                e.stopPropagation();
                const isOpen = childContainer.classList.toggle("open");
                iconSpan.textContent = isOpen ? "▼" : "▶";
            });
        } else {
            const iconSpan = document.createElement("span");
            iconSpan.className = "icon";
            iconSpan.textContent = getFileIcon(item.name);
            el.appendChild(iconSpan);

            const nameSpan = document.createElement("span");
            nameSpan.textContent = item.name;
            el.appendChild(nameSpan);

            el.addEventListener("click", (e) => {
                e.stopPropagation();
                openFile(item.path);

                // Highlight active
                document.querySelectorAll(".tree-item.active").forEach(x => x.classList.remove("active"));
                el.classList.add("active");
            });

            parent.appendChild(el);
        }
    });
}

function getFileIcon(name) {
    const ext = name.split(".").pop().toLowerCase();
    const icons = {
        py: "🐍", js: "📜", ts: "📜", java: "☕", c: "⚙", cpp: "⚙",
        html: "🌐", css: "🎨", json: "📋", md: "📝", txt: "📄",
        h: "⚙", hpp: "⚙", sh: "🐚", rb: "💎",
    };
    return icons[ext] || "📄";
}


// ─── File Operations ────────────────────────────────────────

async function openFile(path) {
    try {
        const resp = await fetch(`/api/read_file?path=${encodeURIComponent(path)}`);
        const data = await resp.json();

        if (data.error) {
            appendChat("error", data.error);
            return;
        }

        state.currentFile = {
            path: data.path,
            content: data.content,
            language: data.language,
        };
        state.modified = false;

        $editorFile.textContent = data.name;
        $codeEditor.value = data.content;
        $btnSave.disabled = true;
        updateLineNumbers();
    } catch (e) {
        appendChat("error", `Failed to open file: ${e.message}`);
    }
}

async function saveFile() {
    if (!state.currentFile) return;

    try {
        const resp = await fetch("/api/write_file", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                path: state.currentFile.path,
                content: $codeEditor.value,
            }),
        });
        const data = await resp.json();

        if (data.success) {
            state.modified = false;
            $btnSave.disabled = true;
            state.currentFile.content = $codeEditor.value;
            appendChat("log", `Saved: ${state.currentFile.path}`);
        } else {
            appendChat("error", "Failed to save file");
        }
    } catch (e) {
        appendChat("error", `Save error: ${e.message}`);
    }
}


// ─── Line Numbers ───────────────────────────────────────────

function updateLineNumbers() {
    const lines = $codeEditor.value.split("\n");
    const nums = [];
    for (let i = 1; i <= lines.length; i++) {
        nums.push(i);
    }
    $lineNumbers.textContent = nums.join("\n");
}

function syncScroll() {
    $lineNumbers.scrollTop = $codeEditor.scrollTop;
}


// ─── Agent Task Execution ───────────────────────────────────

async function sendTask() {
    const task = $chatInput.value.trim();
    if (!task || state.isRunning) return;

    if (!state.projectPath) {
        appendChat("error", "No project loaded. Click '📁 Open Project' first.");
        return;
    }

    state.isRunning = true;
    $btnSend.disabled = true;
    $btnSend.textContent = "⏳ Running...";
    $chatInput.value = "";

    appendChat("user", `> ${task}`);
    appendChat("status", "Starting agent...");

    try {
        const resp = await fetch("/api/run_task", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                task: task,
                repo_path: state.projectPath,
            }),
        });

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // Parse SSE events
            const lines = buffer.split("\n");
            buffer = lines.pop(); // keep incomplete line

            for (const line of lines) {
                if (line.startsWith("data: ")) {
                    try {
                        const event = JSON.parse(line.slice(6));
                        handleAgentEvent(event);
                    } catch {
                        // skip malformed events
                    }
                }
            }
        }
    } catch (e) {
        appendChat("error", `Connection error: ${e.message}`);
    } finally {
        state.isRunning = false;
        $btnSend.disabled = false;
        $btnSend.textContent = "▶ Run";

        // Reload file tree and current file after agent finishes
        if (state.projectPath) {
            loadFileTree(state.projectPath);
        }
        if (state.currentFile) {
            openFile(state.currentFile.path);
        }
    }
}


// ─── SSE Event Handler ─────────────────────────────────────

function handleAgentEvent(event) {
    switch (event.type) {
        case "log":
            handleLogMessage(event.message);
            break;

        case "diff":
            renderDiff(event);
            break;

        case "tool":
            appendChat("tool", `🔧 ${event.tool}: ${event.path}`);
            if (event.result) {
                // Show truncated tool result
                const display = event.result.length > 200
                    ? event.result.substring(0, 200) + "..."
                    : event.result;
                appendChat("log", `   ${display}`);
            }
            break;

        case "result":
            const icon = event.success ? "✅" : "❌";
            appendChat("result", `${icon} ${event.summary}`);
            appendChat("result", `Steps: ${event.steps} | Success: ${event.success}`);
            break;

        case "error":
            appendChat("error", `ERROR: ${event.message}`);
            break;

        case "status":
            appendChat("status", event.message);
            break;

        case "done":
            appendChat("done", "── Agent finished ──");
            break;

        case "heartbeat":
            break;
    }
}

function handleLogMessage(message) {
    // Parse agent step messages for better display
    if (message.startsWith("STEP ") || message.startsWith("--- AGENT")) {
        appendChat("step", message);
    } else if (message.startsWith("DONE:") || message.startsWith("Return code: 0")) {
        appendChat("result", message);
    } else if (message.startsWith("ERROR") || message.startsWith("FAILED") || message.startsWith("REJECTED")) {
        appendChat("error", message);
    } else if (message.startsWith("Mode:") || message.startsWith("Target:")) {
        appendChat("status", message);
    } else {
        appendChat("log", message);
    }
}


// ─── Diff Rendering ─────────────────────────────────────────

function renderDiff(diffData) {
    const block = document.createElement("div");
    block.className = "diff-block";

    // Header
    const header = document.createElement("div");
    header.className = "diff-header";

    const fileName = document.createElement("span");
    fileName.textContent = `Modified: ${diffData.file}`;

    const stats = document.createElement("span");
    stats.className = "diff-stats";
    stats.innerHTML = `<span class="added">+${diffData.added}</span> <span class="removed">-${diffData.removed}</span> lines`;

    header.appendChild(fileName);
    header.appendChild(stats);
    block.appendChild(header);

    // Diff lines
    if (diffData.diff && diffData.diff.length > 0) {
        diffData.diff.forEach(line => {
            const lineEl = document.createElement("div");
            lineEl.className = "diff-line";

            if (line.startsWith("+ ")) {
                lineEl.classList.add("add");
            } else if (line.startsWith("- ")) {
                lineEl.classList.add("del");
            }

            lineEl.textContent = line;
            block.appendChild(lineEl);
        });
    }

    $chatLog.appendChild(block);
    $chatLog.scrollTop = $chatLog.scrollHeight;
}


// ─── Chat Helpers ───────────────────────────────────────────

function appendChat(type, text) {
    const msg = document.createElement("div");
    msg.className = `chat-msg ${type}`;
    msg.textContent = text;
    $chatLog.appendChild(msg);
    $chatLog.scrollTop = $chatLog.scrollHeight;
}


// ─── Resize Panels ──────────────────────────────────────────

function setupResize(handleId, panelId, side) {
    const handle = document.getElementById(handleId);
    const panel = document.getElementById(panelId);

    if (!handle || !panel) return;

    let startX, startWidth;

    handle.addEventListener("mousedown", (e) => {
        startX = e.clientX;
        startWidth = panel.offsetWidth;
        document.addEventListener("mousemove", onMouseMove);
        document.addEventListener("mouseup", onMouseUp);
        e.preventDefault();
    });

    function onMouseMove(e) {
        const dx = e.clientX - startX;
        if (side === "left") {
            panel.style.width = `${startWidth + dx}px`;
        } else {
            panel.style.width = `${startWidth - dx}px`;
        }
    }

    function onMouseUp() {
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
    }
}
