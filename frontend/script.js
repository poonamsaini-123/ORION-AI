// Where is the ORION backend?
//  1. ?api=https://host  in the page URL (explicit override)
//  2. the same origin, if that origin is serving ORION (normal deployment)
//  3. http://127.0.0.1:8000  (e.g. UI opened with VS Code Live Server or from disk)
const DEFAULT_API = "http://127.0.0.1:8000";
let API = DEFAULT_API;

async function isOrion(base) {
    try {
        const response = await fetch(`${base}/health`, { cache: "no-store" });
        const data = await response.json();
        return data.service === "ORION";
    } catch {
        return false;
    }
}

async function resolveApi() {
    const override = new URLSearchParams(window.location.search).get("api");
    if (override) return override.replace(/\/+$/, "");
    if (window.location.protocol !== "file:" && await isOrion(window.location.origin)) {
        return window.location.origin;
    }
    return DEFAULT_API;
}

const UI_VERSION = "1.1.0";

// If index.html is out of date, an element this script expects may not exist.
// Return a detached stand-in instead of null so nothing crashes, and tell the
// user clearly (see the banner below) rather than failing with a cryptic error.
const missingIds = new Set();
const $ = id => {
    const found = document.getElementById(id);
    if (found) return found;
    missingIds.add(id);
    return document.createElement("div");
};

const promptInput = $("prompt");
const responseArea = $("response");
const askButton = $("askButton");
const resultStatus = $("resultStatus");
const speakToggle = $("speakToggle");
const readPlanButton = $("readPlanButton");
const micButton = $("micButton");

const addTaskForm = $("addTaskForm");
const addTaskButton = $("addTaskButton");
const addTaskStatus = $("addTaskStatus");
const toggleAddTask = $("toggleAddTask");
const cancelAddTask = $("cancelAddTask");

const refreshTasksButton = $("refreshTasksButton");
const allTasksList = $("allTasksList");
const allTasksStatus = $("allTasksStatus");

let planInProgress = false;
let tasksLoading = false;
let tasksReloadQueued = false;
let allTasks = [];
let activeFilter = "all";
let lastPlanSpeech = "";
let lastBriefingSpeech = "";


// =========================
// HELPERS
// =========================

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

async function requestJSON(url, options = {}) {
    let response;
    try {
        response = await fetch(url, options);
    } catch {
        throw new Error("Cannot reach the ORION server. Is it running?");
    }

    let data;
    try {
        data = await response.json();
    } catch {
        throw new Error(`Invalid server response (${response.status})`);
    }

    if (!response.ok || data.success === false) {
        throw new Error(data.message || data.detail || `Request failed (${response.status})`);
    }
    return data;
}

const jsonRequest = (method, url, body) =>
    requestJSON(`${API}${url}`, {
        method,
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body)
    });


// =========================
// SPEECH (browser Web Speech API: a simulated voice-assistant experience)
// =========================

const synth = window.speechSynthesis;

function speak(text) {
    if (!synth || !text) return;
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-US";
    utterance.rate = 1;
    synth.speak(utterance);
}

if (synth) {
    $("listenBriefing").hidden = false;
}

const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;

if (SpeechRecognitionAPI) {
    micButton.hidden = false;
    const recognition = new SpeechRecognitionAPI();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    const stopListening = () => {
        micButton.classList.remove("listening");
        micButton.textContent = "🎤 Speak";
    };

    recognition.onresult = event => {
        promptInput.value = event.results[0][0].transcript;
        speakToggle.checked = true;     // answer a spoken request out loud
        askOrion();
    };
    recognition.onend = stopListening;
    recognition.onerror = event => {
        stopListening();
        resultStatus.textContent = event.error === "not-allowed"
            ? "MICROPHONE BLOCKED" : "VOICE ERROR";
    };

    micButton.addEventListener("click", () => {
        if (micButton.classList.contains("listening")) {
            recognition.stop();
            return;
        }
        micButton.classList.add("listening");
        micButton.textContent = "● Listening...";
        try { recognition.start(); } catch { stopListening(); }
    });
}

readPlanButton.addEventListener("click", () => speak(lastPlanSpeech));
$("listenBriefing").addEventListener("click", () => speak(lastBriefingSpeech));


// =========================
// STATUS + MCP PANEL
// =========================

async function checkStatus() {
    const label = $("connectionStatus");
    const dot = $("statusDot");
    try {
        const data = await requestJSON(`${API}/health`);
        label.textContent = `MCP server online · v${data.version}`;
        dot.classList.remove("offline");
    } catch (error) {
        label.textContent = "Backend not running. In a terminal: cd backend && python server.py";
        dot.classList.add("offline");
    }
}

async function loadMcpPanel() {
    $("mcpUrl").textContent = `${API}/mcp`;
    const list = $("mcpToolList");

    try {
        const data = await requestJSON(`${API}/mcp-tools`);
        list.replaceChildren();
        $("mcpToolCount").textContent = `${data.tools.length} tools`;

        for (const tool of data.tools) {
            const card = el("article", "tool-card");
            const top = el("div", "tool-top");
            top.append(el("code", "", tool.name));

            const kind = tool.destructive ? ["DESTRUCTIVE", "danger"]
                : tool.read_only ? ["READ-ONLY", "ok"] : ["WRITES", "warn"];
            top.append(el("span", `badge ${kind[1]}`, kind[0]));

            card.append(top, el("p", "", tool.description));
            list.append(card);
        }
    } catch (error) {
        list.replaceChildren(el("p", "muted", `Could not load tools: ${error.message}`));
    }
}

$("copyMcpUrl").addEventListener("click", async () => {
    const button = $("copyMcpUrl");
    try {
        await navigator.clipboard.writeText($("mcpUrl").textContent);
        button.textContent = "Copied ✓";
    } catch {
        button.textContent = "Press Ctrl+C";
    }
    setTimeout(() => { button.textContent = "Copy"; }, 1800);
});


// =========================
// DAILY BRIEFING
// =========================

async function loadBriefing() {
    try {
        const data = await requestJSON(`${API}/briefing`);
        lastBriefingSpeech = data.spoken;
        $("briefingText").textContent = data.spoken;

        const chips = $("briefingChips");
        chips.replaceChildren();
        const addChip = (text, kind) => chips.append(el("span", `chip ${kind}`, text));

        if (data.overdue.length) addChip(`${data.overdue.length} overdue`, "danger");
        if (data.due_today.length) addChip(`${data.due_today.length} due today`, "warn");
        if (data.due_soon.length) addChip(`${data.due_soon.length} due soon`, "info");
        addChip(`${data.pending} pending`, "neutral");
        addChip(`${data.completed} done`, "ok");
        if (data.next_event) addChip(`Next: ${data.next_event.event} · ${data.next_event.time}`, "neutral");

        $("progressFill").style.width = `${data.progress_percent}%`;
        $("progressBar").setAttribute("aria-valuenow", String(data.progress_percent));
        $("progressLabel").textContent = `${data.progress_percent}% of your tasks completed`;
        return data;
    } catch (error) {
        $("briefingText").textContent = `Could not load the briefing: ${error.message}`;
        return null;
    }
}


// =========================
// PLAN
// =========================

const BRIEFING_INTENT =
    /\b(briefing|my day|summary|overview|how am i doing|what('?s| is)? (due|overdue|up|next)|anything (due|overdue))\b/i;

function useExample(text) {
    promptInput.value = text;
    promptInput.focus();
}

document.querySelectorAll(".suggestions button[data-prompt]").forEach(button => {
    button.addEventListener("click", () => useExample(button.dataset.prompt));
});

function renderPlan(plan) {
    responseArea.replaceChildren();

    if (plan.length === 0) {
        responseArea.append(el("p", "muted", "No pending tasks were found for this plan."));
        return;
    }

    let totalMinutes = 0;

    for (const item of plan) {
        totalMinutes += Number(item.time) || 0;

        const card = el("article", "plan-card");
        const top = el("div", "plan-card-top");
        top.append(el("h4", "", item.task || "Untitled task"));

        const priority = el("span", "priority", `${String(item.priority || "planned").toUpperCase()} PRIORITY`);
        if (item.priority === "Medium") priority.classList.add("medium");
        if (item.priority === "Low") priority.classList.add("low");
        top.append(priority);

        const time = el("div", "plan-time",
            `${item.start_time} → ${item.end_time} · ${item.time} min`);
        const reason = el("div", "plan-reason", item.reason || "");

        const completeButton = el("button", "complete-button", "✓ Mark Complete");
        completeButton.type = "button";
        completeButton.addEventListener("click", async () => {
            completeButton.disabled = true;
            completeButton.textContent = "Completing...";
            try {
                const result = await jsonRequest("POST", "/complete-task", { task_id: item.id });
                await refreshAll();
                await generatePlan({ announce: false });
                resultStatus.textContent = result.message.toUpperCase();
            } catch (error) {
                completeButton.disabled = false;
                completeButton.textContent = "Try Again";
                resultStatus.textContent = error.message;
            }
        });

        card.append(top, time, reason, completeButton);
        responseArea.append(card);
    }

    responseArea.append(el("div", "total-time", `Total planned time: ${totalMinutes} minutes`));
}

async function generatePlan({ announce = true } = {}) {
    const prompt = promptInput.value.trim();

    if (!prompt) {
        promptInput.focus();
        promptInput.placeholder = "Enter a request first...";
        return;
    }
    if (planInProgress) return;
    planInProgress = true;

    askButton.disabled = true;
    askButton.textContent = "Working...";
    resultStatus.textContent = "PROCESSING";

    try {
        const data = await jsonRequest("POST", "/plan", { prompt });
        renderPlan(data.response);
        lastPlanSpeech = data.spoken;
        readPlanButton.hidden = !synth;
        resultStatus.textContent = "PLAN GENERATED";
        if (announce && speakToggle.checked) speak(data.spoken);
    } catch (error) {
        responseArea.replaceChildren(el("div", "error-message", `Could not generate plan: ${error.message}`));
        resultStatus.textContent = "ERROR";
    } finally {
        planInProgress = false;
        askButton.disabled = false;
        askButton.textContent = "Generate plan ↗";
    }
}

async function askOrion() {
    const prompt = promptInput.value.trim();

    if (BRIEFING_INTENT.test(prompt)) {
        resultStatus.textContent = "BRIEFING";
        const data = await loadBriefing();
        $("briefing").scrollIntoView({ behavior: "smooth", block: "start" });
        if (data && speakToggle.checked) speak(data.spoken);
        return;
    }
    return generatePlan();
}

askButton.addEventListener("click", askOrion);
promptInput.addEventListener("keydown", event => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) askOrion();
});


// =========================
// TASKS
// =========================

function setAddTaskFormOpen(open) {
    addTaskForm.hidden = !open;
    toggleAddTask.setAttribute("aria-expanded", String(open));
    toggleAddTask.textContent = open ? "− Cancel" : "+ New Task";
    if (open) $("taskTitle").focus();
}

toggleAddTask.addEventListener("click", () => setAddTaskFormOpen(addTaskForm.hidden));
cancelAddTask.addEventListener("click", () => {
    addTaskForm.reset();
    addTaskStatus.textContent = "";
    setAddTaskFormOpen(false);
});

// Re-plan after any change, but only if the user already asked for a plan.
async function afterTaskChange(message, statusEl = allTasksStatus) {
    await refreshAll();
    statusEl.textContent = message || "";
    if (lastPlanSpeech && promptInput.value.trim() && !BRIEFING_INTENT.test(promptInput.value)) {
        await generatePlan({ announce: false });
    }
}

function createEditForm(task, card) {
    if (card.querySelector(".inline-edit-form")) return;

    const form = el("form", "inline-edit-form");

    const field = (labelText, control) => {
        const label = el("label", "", labelText);
        label.append(control);
        return label;
    };

    const titleInput = el("input");
    titleInput.type = "text";
    titleInput.value = task.title;
    titleInput.maxLength = 200;
    titleInput.required = true;

    const deadlineInput = el("input");
    deadlineInput.type = "text";
    deadlineInput.value = task.deadline || "";
    deadlineInput.maxLength = 100;

    const prioritySelect = el("select");
    ["High", "Medium", "Low"].forEach(value => {
        const option = el("option", "", value);
        option.value = value;
        prioritySelect.append(option);
    });
    prioritySelect.value = task.priority || "Medium";

    const message = el("p", "edit-task-status");
    message.setAttribute("role", "status");

    const saveButton = el("button", "save-button", "Save Changes");
    saveButton.type = "submit";
    const cancelButton = el("button", "button-secondary", "Cancel");
    cancelButton.type = "button";
    cancelButton.addEventListener("click", () => form.remove());

    const actions = el("div", "task-actions");
    actions.append(saveButton, cancelButton);
    form.append(field("Task title", titleInput), field("Deadline", deadlineInput),
        field("Priority", prioritySelect), message, actions);
    card.append(form);
    titleInput.focus();

    form.addEventListener("submit", async event => {
        event.preventDefault();
        saveButton.disabled = cancelButton.disabled = true;
        saveButton.textContent = "Saving...";
        try {
            const data = await jsonRequest("PUT", "/edit-task", {
                task_id: task.id,
                title: titleInput.value.trim(),
                deadline: deadlineInput.value.trim() || "Not specified",
                priority: prioritySelect.value
            });
            await afterTaskChange(data.message);
        } catch (error) {
            message.textContent = error.message;
            saveButton.disabled = cancelButton.disabled = false;
            saveButton.textContent = "Save Changes";
        }
    });
}

async function runTaskAction(label, action) {
    allTasksStatus.textContent = label;
    try {
        const data = await action();
        await afterTaskChange(data.message);
    } catch (error) {
        allTasksStatus.textContent = `Could not complete that action: ${error.message}`;
    }
}

function renderTasks() {
    const visible = allTasks.filter(task =>
        activeFilter === "all" ||
        (activeFilter === "completed" ? task.completed : !task.completed));

    $("allTasksCount").textContent =
        `${visible.length} ${visible.length === 1 ? "task" : "tasks"}`;
    allTasksList.replaceChildren();

    if (visible.length === 0) {
        allTasksList.append(el("p", "muted",
            allTasks.length ? "No tasks match this filter." : "No tasks yet. Add one to get started."));
        return;
    }

    for (const task of visible) {
        const card = el("article", `all-task-card${task.completed ? " is-done" : ""}`);

        const heading = el("div", "all-task-heading");
        heading.append(el("h3", "", task.title),
            el("span", `task-status ${task.completed ? "completed" : "pending"}`,
                task.completed ? "Completed" : "Pending"));

        const meta = el("div", "task-meta");
        meta.append(el("span", "", `Deadline: ${task.deadline || "Not specified"}`),
            el("span", `badge ${String(task.priority || "Medium").toLowerCase()}`,
                `${task.priority || "Medium"} priority`));

        const actions = el("div", "task-actions");

        const toggle = el("button", task.completed ? "button-secondary" : "complete-button",
            task.completed ? "↺ Reopen" : "✓ Complete");
        toggle.type = "button";
        toggle.addEventListener("click", () => runTaskAction(
            task.completed ? "Reopening..." : "Completing...",
            () => jsonRequest("POST", task.completed ? "/reopen-task" : "/complete-task",
                { task_id: task.id })));

        const edit = el("button", "edit-button", "✎ Edit");
        edit.type = "button";
        edit.addEventListener("click", () => createEditForm(task, card));

        const remove = el("button", "delete-button", "Delete");
        remove.type = "button";
        remove.addEventListener("click", () => {
            if (!window.confirm(`Delete "${task.title}" permanently?\n\nThis cannot be undone.`)) return;
            runTaskAction(`Deleting "${task.title}"...`,
                () => jsonRequest("DELETE", `/delete-task/${encodeURIComponent(task.id)}`));
        });

        actions.append(toggle, edit, remove);
        card.append(heading, meta, actions);
        allTasksList.append(card);
    }
}

document.querySelectorAll(".filter").forEach(button => {
    button.addEventListener("click", () => {
        activeFilter = button.dataset.filter;
        document.querySelectorAll(".filter").forEach(b => {
            const on = b === button;
            b.classList.toggle("active", on);
            b.setAttribute("aria-pressed", String(on));
        });
        renderTasks();
    });
});

async function loadAllTasks() {
    // If a refresh is already running, run once more afterwards so the list
    // never shows stale data.
    if (tasksLoading) {
        tasksReloadQueued = true;
        return;
    }
    tasksLoading = true;
    refreshTasksButton.disabled = true;

    try {
        const data = await requestJSON(`${API}/tasks`);
        allTasks = data.tasks;
        $("totalTasks").textContent = data.total;
        $("pendingTasks").textContent = data.pending;
        $("completedTasks").textContent = data.completed;
        renderTasks();
    } catch (error) {
        allTasksList.replaceChildren(el("p", "muted", `Could not load tasks: ${error.message}`));
    } finally {
        tasksLoading = false;
        refreshTasksButton.disabled = false;
        if (tasksReloadQueued) {
            tasksReloadQueued = false;
            loadAllTasks();
        }
    }
}

const refreshAll = () => Promise.all([loadAllTasks(), loadBriefing(), loadSchedule()]);

refreshTasksButton.addEventListener("click", refreshAll);

addTaskForm.addEventListener("submit", async event => {
    event.preventDefault();

    const restoreButton = () => {
        addTaskButton.disabled = false;
        addTaskButton.textContent = "Save Task";
    };

    addTaskButton.disabled = true;
    addTaskButton.textContent = "Saving...";
    addTaskStatus.textContent = "";

    let data;
    try {
        data = await jsonRequest("POST", "/add-task", {
            title: $("taskTitle").value.trim(),
            deadline: $("taskDeadline").value.trim() || "Not specified",
            priority: $("taskPriority").value
        });
    } catch (error) {
        addTaskStatus.textContent = error.message;
        restoreButton();
        return;
    }

    // Saved: free the form immediately, then refresh the lists in the background.
    addTaskForm.reset();
    setAddTaskFormOpen(false);
    restoreButton();
    await afterTaskChange(data.message);
});


// =========================
// SCHEDULE
// =========================

const scheduleList = $("scheduleList");
const addEventForm = $("addEventForm");
const addEventButton = $("addEventButton");
const addEventStatus = $("addEventStatus");
const scheduleStatus = $("scheduleStatus");
const toggleAddEvent = $("toggleAddEvent");

function setAddEventFormOpen(open) {
    addEventForm.hidden = !open;
    toggleAddEvent.setAttribute("aria-expanded", String(open));
    toggleAddEvent.textContent = open ? "− Cancel" : "+ New Event";
    if (open) $("eventName").focus();
}

toggleAddEvent.addEventListener("click", () => setAddEventFormOpen(addEventForm.hidden));
$("cancelAddEvent").addEventListener("click", () => {
    addEventForm.reset();
    addEventStatus.textContent = "";
    setAddEventFormOpen(false);
});

// "2:30 PM" + 90 min -> "4:00 PM"
function endTime(time, minutes) {
    const match = /^(\d{1,2}):(\d{2}) (AM|PM)$/.exec(time);
    if (!match) return "";
    let hour = Number(match[1]) % 12 + (match[3] === "PM" ? 12 : 0);
    const total = (hour * 60 + Number(match[2]) + Number(minutes)) % (24 * 60);
    const h24 = Math.floor(total / 60);
    return `${h24 % 12 || 12}:${String(total % 60).padStart(2, "0")} ${h24 >= 12 ? "PM" : "AM"}`;
}

async function loadSchedule() {
    try {
        const data = await requestJSON(`${API}/schedule`);
        scheduleList.replaceChildren();

        if (data.events.length === 0) {
            scheduleList.append(el("p", "muted", "No events yet. Add your classes so ORION can plan around them."));
            return;
        }

        for (const event of data.events) {
            const row = el("article", "event-row");
            row.append(
                el("span", "event-time", `${event.time} → ${endTime(event.time, event.duration)}`),
                el("span", "event-name", event.event),
                el("span", "event-length", `${event.duration} min`));

            const remove = el("button", "delete-button", "Delete");
            remove.type = "button";
            remove.setAttribute("aria-label", `Delete ${event.event}`);
            remove.addEventListener("click", async () => {
                if (!window.confirm(`Remove "${event.event}" from today's schedule?`)) return;
                scheduleStatus.textContent = "Removing...";
                try {
                    const result = await jsonRequest("DELETE", `/delete-event/${encodeURIComponent(event.id)}`);
                    await afterTaskChange(result.message, scheduleStatus);
                } catch (error) {
                    scheduleStatus.textContent = `Could not remove the event: ${error.message}`;
                }
            });

            row.append(remove);
            scheduleList.append(row);
        }
    } catch (error) {
        scheduleList.replaceChildren(el("p", "muted", `Could not load schedule: ${error.message}`));
    }
}

addEventForm.addEventListener("submit", async event => {
    event.preventDefault();

    const restore = () => {
        addEventButton.disabled = false;
        addEventButton.textContent = "Save Event";
    };
    addEventButton.disabled = true;
    addEventButton.textContent = "Saving...";
    addEventStatus.textContent = "";

    let data;
    try {
        data = await jsonRequest("POST", "/add-event", {
            name: $("eventName").value.trim(),
            time: $("eventTime").value.trim(),
            duration_minutes: Number($("eventDuration").value) || 60
        });
    } catch (error) {
        addEventStatus.textContent = error.message;
        restore();
        return;
    }

    addEventForm.reset();
    $("eventDuration").value = 60;
    setAddEventFormOpen(false);
    restore();
    await afterTaskChange(data.message, scheduleStatus);
});


// =========================
// VERSION CHECK
// =========================

(function checkPageVersion() {
    const meta = document.querySelector('meta[name="orion-ui-version"]');
    const pageVersion = meta ? meta.content : "unknown";

    if (pageVersion === UI_VERSION && missingIds.size === 0) return;

    console.warn("ORION: index.html is version", pageVersion, "but script.js is",
        UI_VERSION, "| missing elements:", [...missingIds]);

    const banner = el("div", "version-banner");
    banner.setAttribute("role", "alert");
    banner.textContent =
        `This page's index.html (version ${pageVersion}) does not match script.js ` +
        `(version ${UI_VERSION}). Replace the whole frontend folder with the one from ` +
        `the latest zip, then hard-refresh (Ctrl+Shift+R). Some features may be missing until then.`;
    document.body.prepend(banner);
})();


// =========================
// INITIALIZE
// =========================

resolveApi().then(base => {
    API = base;
    checkStatus();
    loadAllTasks();
    loadBriefing();
    loadSchedule();
    loadMcpPanel();
});