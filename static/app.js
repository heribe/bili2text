// 全局状态管理
let authToken = localStorage.getItem("bili2text_token") || "";
let activeTaskId = null;
let activeSSE = null;
let currentTaskData = null; // 存储当前查看的任务详情

// DOM 元素引用
const lockScreen = document.getElementById("lock-screen");
const loginForm = document.getElementById("login-form");
const accessPasswordInput = document.getElementById("access-password");
const loginError = document.getElementById("login-error");

const connectionLamp = document.getElementById("connection-lamp");
const connectionText = document.getElementById("connection-text");

const btnCreateTask = document.getElementById("btn-create-task");
const taskListContainer = document.getElementById("task-list");
const taskForm = document.getElementById("task-form");
const videoUrlInput = document.getElementById("video-url");
const submitError = document.getElementById("submit-error");

// 右侧面板
const panelNewTask = document.getElementById("panel-new-task");
const panelProcessing = document.getElementById("panel-processing");
const panelDetail = document.getElementById("panel-detail");

// 进度页元素
const procVideoTitle = document.getElementById("proc-video-title");
const procVideoDesc = document.getElementById("proc-video-desc");
const procVideoUrl = document.getElementById("proc-video-url");
const procProgressFill = document.getElementById("proc-progress-fill");
const procStepMsg = document.getElementById("proc-step-msg");
const procPercent = document.getElementById("proc-percent");
const btnRetryTask = document.getElementById("btn-retry-task");

// 详情页元素
const detailVideoTitle = document.getElementById("detail-video-title");
const detailVideoDesc = document.getElementById("detail-video-desc");
const transcriptFlow = document.getElementById("transcript-flow");
const btnViewLog = document.getElementById("btn-view-log");
const btnCopyAll = document.getElementById("btn-copy-all");
const tabBtnFinal = document.getElementById("tab-btn-final");
const tabBtnRaw = document.getElementById("tab-btn-raw");
const sourceSelector = document.getElementById("source-selector");
const radioBiliAi = document.querySelector('input[name="view-source"][value="bili_ai"]');
const radioWhisper = document.querySelector('input[name="view-source"][value="whisper"]');
let currentViewMode = "final"; // "final" 或 "raw"
let currentViewSource = "bili_ai"; // "bili_ai" 或 "whisper"

document.querySelectorAll('input[name="view-source"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
        currentViewSource = e.target.value;
        renderTranscriptCurrentMode();
    });
});

/* ==========================================================================
   1. 基础认证与 API 拦截器
   ========================================================================== */

function checkAuth() {
    if (!authToken) {
        lockScreen.classList.remove("hidden");
    } else {
        lockScreen.classList.add("hidden");
        initApp();
    }
}

function logout() {
    authToken = "";
    localStorage.removeItem("bili2text_token");
    activeTaskId = null;
    if (activeSSE) {
        activeSSE.close();
        activeSSE = null;
    }
    lockScreen.classList.remove("hidden");
    connectionLamp.className = "lamp";
    connectionText.innerText = "未连接";
}

// 统一 API 异步请求封装
async function apiRequest(url, options = {}) {
    if (!options.headers) {
        options.headers = {};
    }
    
    // 如果有凭证，带上 Bearer 头
    if (authToken) {
        options.headers["Authorization"] = `Bearer ${authToken}`;
    }
    
    try {
        const response = await fetch(url, options);
        
        if (response.status === 401) {
            // Token 失效，执行登出重新锁屏
            logout();
            throw new Error("会话过期或无权访问");
        }
        
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || `请求失败 (${response.status})`);
        }
        
        return await response.json();
    } catch (err) {
        console.error("API Error:", err);
        throw err;
    }
}

// 登录表单提交
loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginError.innerText = "";
    
    const password = accessPasswordInput.value.trim();
    try {
        const data = await apiRequest("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password })
        });
        
        authToken = data.token;
        localStorage.setItem("bili2text_token", authToken);
        
        // 成功登录，平滑淡出锁屏界面
        lockScreen.classList.add("hidden");
        accessPasswordInput.value = "";
        
        initApp();
    } catch (err) {
        loginError.innerText = err.message || "登录校验失败";
    }
});

/* ==========================================================================
   2. 页面与面板切换逻辑
   ========================================================================== */

function switchPanel(panel) {
    [panelNewTask, panelProcessing, panelDetail].forEach(p => {
        p.classList.remove("active");
    });
    panel.classList.add("active");
}

// “新建转录任务”按钮点击
btnCreateTask.addEventListener("click", () => {
    activeTaskId = null;
    // 取消侧边栏所有高亮
    document.querySelectorAll(".task-item").forEach(item => {
        item.classList.remove("active");
    });
    switchPanel(panelNewTask);
    videoUrlInput.focus();
    submitError.innerText = "";
});

/* ==========================================================================
   3. 历史任务列表 CRUD
   ========================================================================== */

async function fetchTaskList(autoSelectId = null) {
    try {
        const tasks = await apiRequest("/api/tasks");
        renderTaskList(tasks, autoSelectId);
    } catch (err) {
        console.error("加载列表失败:", err);
    }
}

function renderTaskList(tasks, autoSelectId) {
    taskListContainer.innerHTML = "";
    
    if (tasks.length === 0) {
        taskListContainer.innerHTML = '<div class="list-empty">暂无转录记录</div>';
        return;
    }
    
    tasks.forEach(task => {
        const item = document.createElement("div");
        item.className = `task-item ${task.id === activeTaskId ? 'active' : ''}`;
        item.setAttribute("data-id", task.id);
        
        // 解析状态显示
        let statusClass = "pending";
        let statusText = "排队中";
        
        if (task.status === "processing") {
            statusClass = "processing";
            statusText = "处理中";
        } else if (task.status === "completed") {
            statusClass = "completed";
            statusText = "已完成";
        } else if (task.status === "failed") {
            statusClass = "failed";
            statusText = "失败";
        }
        
        // 格式化时间戳
        const dateStr = task.created_at ? new Date(task.created_at).toLocaleString('zh-CN', {
            month: 'numeric',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        }) : "";
        
        // 组装 HTML
        item.innerHTML = `
            <div class="task-item-header">
                <div class="task-item-title" title="${task.title || '正在解析标题...'}">${task.title || '正在解析标题...'}</div>
                <button class="btn-delete-task" title="删除记录">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
            </div>
            <div class="task-item-footer">
                <span>${dateStr}</span>
                <span class="badge-status ${statusClass}">${statusText}</span>
            </div>
        `;
        
        // 点击任务项查看详情或进度
        item.addEventListener("click", (e) => {
            // 如果点的是删除按钮，防止触发选择事件
            if (e.target.closest(".btn-delete-task")) return;
            selectTask(task);
        });
        
        // 删除按钮点击事件
        const btnDelete = item.querySelector(".btn-delete-task");
        btnDelete.addEventListener("click", async (e) => {
            e.stopPropagation();
            if (confirm(`确定要永久删除转录记录 "${task.title || '未命名记录'}" 吗？`)) {
                try {
                    await apiRequest(`/api/tasks/${task.id}`, { method: "DELETE" });
                    
                    // 如果删掉的是当前查看的任务，切回到表单面板
                    if (activeTaskId === task.id) {
                        activeTaskId = null;
                        if (activeSSE) {
                            activeSSE.close();
                            activeSSE = null;
                        }
                        switchPanel(panelNewTask);
                    }
                    
                    fetchTaskList();
                } catch (err) {
                    alert(`删除失败: ${err.message}`);
                }
            }
        });
        
        taskListContainer.appendChild(item);
    });
    
    // 如果指定了需要自动选中的项
    if (autoSelectId) {
        const targetTask = tasks.find(t => t.id === autoSelectId);
        if (targetTask) {
            selectTask(targetTask);
        }
    }
}

// 选择特定任务处理
async function selectTask(task) {
    activeTaskId = task.id;
    
    // 更新侧边栏高亮状态
    document.querySelectorAll(".task-item").forEach(item => {
        if (item.getAttribute("data-id") === task.id) {
            item.classList.add("active");
        } else {
            item.classList.remove("active");
        }
    });
    
    try {
        const fullTask = await apiRequest(`/api/tasks/${task.id}`);
        currentTaskData = fullTask;
        
        if (fullTask.status === "completed") {
            if (activeSSE) {
                activeSSE.close();
                activeSSE = null;
            }
            showTaskDetail(fullTask, "final");
        } else if (fullTask.status === "failed") {
            if (activeSSE) {
                activeSSE.close();
                activeSSE = null;
            }
            setupFailedPanel(fullTask);
        } else {
            // pending 或 processing
            startProgressListener(fullTask.id);
            if (fullTask.raw_result && Object.keys(JSON.parse(fullTask.raw_result || "{}")).length > 0) {
                showTaskDetail(fullTask, "raw");
            } else {
                setupProcessingPanel(fullTask);
            }
        }
    } catch (err) {
        console.error("加载任务详情失败:", err);
    }
}

/* ==========================================================================
   4. 进度推送与 SSE 长连接
   ========================================================================== */

function setupProcessingPanel(task) {
    procVideoTitle.innerText = task.title || "正在拉取视频信息...";
    procVideoDesc.innerText = task.description || "请稍候，系统正在从 B 站下载纯音频轨...";
    
    // 设置视频链接
    if (task.bili_url) {
        procVideoUrl.href = task.bili_url;
        procVideoUrl.style.display = "inline-flex";
    } else if (task.bvid) {
        procVideoUrl.href = `https://www.bilibili.com/video/${task.bvid}`;
        procVideoUrl.style.display = "inline-flex";
    } else {
        procVideoUrl.href = "#";
        procVideoUrl.style.display = "none";
    }
    
    procProgressFill.style.width = "0%";
    procPercent.innerText = "--%";
    procStepMsg.innerText = "正在同步实时进度...";
    btnRetryTask.style.display = "none";
    switchPanel(panelProcessing);
}

function setupFailedPanel(task) {
    procVideoTitle.innerText = task.title || "解析元数据失败";
    procVideoDesc.innerText = task.description || "视频链接或网络解析异常。";
    
    // 设置视频链接
    if (task.bili_url) {
        procVideoUrl.href = task.bili_url;
        procVideoUrl.style.display = "inline-flex";
    } else if (task.bvid) {
        procVideoUrl.href = `https://www.bilibili.com/video/${task.bvid}`;
        procVideoUrl.style.display = "inline-flex";
    } else {
        procVideoUrl.href = "#";
        procVideoUrl.style.display = "none";
    }
    
    procProgressFill.style.width = "100%";
    procProgressFill.style.background = "var(--accent-red)";
    procPercent.innerText = "FAIL";
    procStepMsg.innerHTML = `<span style="color: var(--accent-red);">任务处理失败: ${task.error_msg || '未知错误'}</span>`;
    btnRetryTask.style.display = "inline-flex";
    switchPanel(panelProcessing);
}

function startProgressListener(taskId) {
    // 关闭前一个 SSE 监听，防止连接重叠泄露
    if (activeSSE) {
        activeSSE.close();
    }
    
    // 实例化 EventSource，并在 URL Query 参数中安全地传入校验 Token
    const sseUrl = `/api/tasks/${taskId}/sse?token=${authToken}`;
    const sse = new EventSource(sseUrl);
    activeSSE = sse;
    
    connectionLamp.className = "lamp connected";
    connectionText.innerText = "正在监听进度";
    
    sse.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            
            // 实时更新进度条与状态消息
            procProgressFill.style.background = "linear-gradient(90deg, var(--accent-blue), var(--accent-indigo), var(--accent-purple), var(--accent-blue))";
            procProgressFill.style.backgroundSize = "200% 100%";
            procProgressFill.style.width = `${data.progress}%`;
            procPercent.innerText = `${data.progress}%`;
            procStepMsg.innerText = data.msg;
            
            // 如果得到了原始结果，且当前正在看这个任务，跳转到详情页看草稿
            if (activeTaskId === taskId && (data.step === "diarize_and_merge" || data.has_raw)) {
                apiRequest(`/api/tasks/${taskId}`).then(fullTask => {
                    if (activeTaskId === taskId) {
                        showTaskDetail(fullTask, "raw");
                    }
                });
            }
            
            // 如果解析到了标题，并且当前界面上还是默认文本，则实时更新标题
            if (data.step !== "parse") {
                // 转录开始后，重新刷新列表使其标题能够正确显示
                if (procVideoTitle.innerText === "正在拉取视频信息...") {
                    fetchTaskList();
                    // 重新获取该任务信息填充界面
                    apiRequest(`/api/tasks/${taskId}`).then(task => {
                        procVideoTitle.innerText = task.title || "已获取标题";
                        procVideoDesc.innerText = task.description || "无简介";
                        
                        // 动态更新视频链接
                        if (task.bili_url) {
                            procVideoUrl.href = task.bili_url;
                            procVideoUrl.style.display = "inline-flex";
                        } else if (task.bvid) {
                            procVideoUrl.href = `https://www.bilibili.com/video/${task.bvid}`;
                            procVideoUrl.style.display = "inline-flex";
                        }
                    });
                }
            }
            
            // 任务终结成功：关闭 SSE 并跳转详情
            if (data.step === "completed") {
                sse.close();
                activeSSE = null;
                connectionLamp.className = "lamp connected";
                connectionText.innerText = "监听已开启";
                
                // 刷新侧边栏并直接跳转详情面板 (传入 taskId 自动选择)
                fetchTaskList(taskId);
            }
            
            // 任务终结失败：关闭 SSE 并显示红色警报与重试按钮
            if (data.step === "failed") {
                sse.close();
                activeSSE = null;
                connectionLamp.className = "lamp connected";
                connectionText.innerText = "监听已开启";
                
                // 刷新侧边栏
                fetchTaskList();
                procProgressFill.style.width = "100%";
                procProgressFill.style.background = "var(--accent-red)";
                procPercent.innerText = "FAIL";
                procStepMsg.innerHTML = `<span style="color: var(--accent-red);">${data.msg}</span>`;
                btnRetryTask.style.display = "inline-flex";
            }
            
        } catch (err) {
            console.error("解析 SSE 进度数据失败:", err);
        }
    };
    
    sse.onerror = (err) => {
        console.error("SSE Connection Error:", err);
        connectionLamp.className = "lamp";
        connectionText.innerText = "监听连接断开";
        sse.close();
    };
}

/* ==========================================================================
   5. 新建任务表单提交
   ========================================================================== */

taskForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    submitError.innerText = "";
    
    const url = videoUrlInput.value.trim();
    const language = document.querySelector('input[name="lang-mode"]:checked').value;
    const asr_model = document.querySelector('input[name="asr-model"]:checked').value;
    const transcribe_source = document.querySelector('input[name="transcribe-source"]:checked').value;
    
    try {
        const btnSubmit = document.getElementById("btn-submit-task");
        btnSubmit.disabled = true;
        btnSubmit.querySelector("span").innerText = "提交中...";
        
        const data = await apiRequest("/api/tasks", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url, language, asr_model, transcribe_source })
        });
        
        videoUrlInput.value = "";
        btnSubmit.disabled = false;
        btnSubmit.querySelector("span").innerText = "开始转录音频";
        
        activeTaskId = data.task_id;
        
        // 瞬间触发列表刷新，让侧边栏展现排队状态
        await fetchTaskList();
        
        // 切换详情面板并开启长连接监听
        const dummyTask = {
            id: data.task_id,
            status: "pending",
            title: "正在拉取视频信息...",
            description: "请稍候，系统正在从 B 站下载纯音频轨...",
            bili_url: videoUrlInput.value ? videoUrlInput.value.trim() : ""
        };
        setupProcessingPanel(dummyTask);
        startProgressListener(data.task_id);
        
    } catch (err) {
        submitError.innerText = err.message || "任务提交失败，请重试";
        const btnSubmit = document.getElementById("btn-submit-task");
        btnSubmit.disabled = false;
        btnSubmit.querySelector("span").innerText = "开始转录音频";
    }
});

/* ==========================================================================
   6. 详情页渲染与剧本复制
   ========================================================================== */

// 格式化时间戳显示
function formatTime(seconds) {
    if (seconds === undefined || seconds === null || isNaN(seconds)) {
        return "00:00";
    }
    const total_seconds = Math.floor(seconds);
    const hours = Math.floor(total_seconds / 3600);
    const minutes = Math.floor((total_seconds % 3600) / 60);
    const secs = total_seconds % 60;
    
    if (hours > 0) {
        return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
    return `${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

// 渲染当前所选模式的剧本
function renderTranscriptCurrentMode() {
    transcriptFlow.innerHTML = "";
    
    if (!currentTaskData) return;
    
    let sourceData = {};
    let isRawMode = currentViewMode === "raw";
    
    try {
        if (isRawMode) {
            sourceData = typeof currentTaskData.raw_result === "string" 
                ? JSON.parse(currentTaskData.raw_result) 
                : (currentTaskData.raw_result || {});
        } else {
            sourceData = typeof currentTaskData.result === "string" 
                ? JSON.parse(currentTaskData.result) 
                : (currentTaskData.result || {});
        }
    } catch (e) {
        console.error("解析剧本 JSON 失败:", e);
        transcriptFlow.innerHTML = '<div class="error-msg">剧本内容解析失败，格式异常。</div>';
        return;
    }
    
    const hasBili = sourceData && sourceData["bili_ai"] && sourceData["bili_ai"].length > 0;
    const hasWhisper = sourceData && sourceData["whisper"] && sourceData["whisper"].length > 0;
    
    if (hasBili || hasWhisper) {
        sourceSelector.style.display = "flex";
        radioBiliAi.parentElement.style.display = hasBili ? "flex" : "none";
        radioWhisper.parentElement.style.display = hasWhisper ? "flex" : "none";
        
        // Auto select fallback
        if (!sourceData[currentViewSource] || sourceData[currentViewSource].length === 0) {
            if (hasBili) {
                currentViewSource = "bili_ai";
                radioBiliAi.checked = true;
            } else if (hasWhisper) {
                currentViewSource = "whisper";
                radioWhisper.checked = true;
            }
        }
    } else {
        sourceSelector.style.display = "none";
    }
    
    let segments = sourceData[currentViewSource] || [];
    
    if (segments.length === 0) {
        transcriptFlow.innerHTML = `<div class="list-empty">${isRawMode ? '暂无语音识别草稿' : '大模型合并剧本正在生成中，请耐心等候...'}</div>`;
        return;
    }
    
    // 如果是发生错误的大模型结果
    if (!isRawMode && segments.length === 1 && segments[0].error) {
        transcriptFlow.innerHTML = `
            <div class="list-empty" style="color: var(--accent-red); margin-bottom: 20px; line-height: 1.5;">
                大模型排版失败: ${segments[0].error}
            </div>
            <div style="text-align: center;">
                <button id="btn-retry-llm-action" class="btn-submit" style="width: auto; padding: 10px 30px; font-size: 14px;">重试大模型推理</button>
            </div>
        `;
        document.getElementById("btn-retry-llm-action").addEventListener("click", async () => {
            document.getElementById("btn-retry-llm-action").disabled = true;
            document.getElementById("btn-retry-llm-action").innerText = "正在重新投递队列...";
            try {
                await apiRequest(`/api/tasks/${currentTaskData.id}/retry_llm`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ source: currentViewSource })
                });
                // 重新绑定进度监听，并跳回处理界面
                startProgressListener(currentTaskData.id);
                switchPanel(panelProcessing);
            } catch (err) {
                alert("重试失败: " + err.message);
                document.getElementById("btn-retry-llm-action").disabled = false;
                document.getElementById("btn-retry-llm-action").innerText = "重试大模型推理";
            }
        });
        return;
    }
    
    segments.forEach((seg, idx) => {
        const lineDiv = document.createElement("div");
        lineDiv.className = "script-line";
        
        const start = seg.start || 0.0;
        const end = seg.end || 0.0;
        const timeStr = `[${formatTime(start)} - ${formatTime(end)}]`;
        
        let speakerHtml = "";
        if (isRawMode) {
            speakerHtml = `<span class="speaker-badge sp-raw">说话人 (草稿)</span>`;
        } else {
            const speakerId = seg.speaker !== undefined ? seg.speaker : 0;
            const spClass = `sp-${speakerId % 5}`;
            speakerHtml = `<span class="speaker-badge ${spClass}">说话人 ${speakerId}</span>`;
        }
        
        lineDiv.innerHTML = `
            <div class="script-time">${timeStr}</div>
            ${speakerHtml}
            <div class="script-text">${seg.text || ""}</div>
        `;
        transcriptFlow.appendChild(lineDiv);
    });
}

// 展示特定任务的剧本详情
function showTaskDetail(task, defaultMode = null) {
    currentTaskData = task;
    
    // 设置标题与描述
    detailVideoTitle.innerText = task.title || "未命名记录";
    detailVideoDesc.innerText = task.description || "暂无视频简介。";
    
    // 设置视频跳转链接
    const videoUrlLink = document.getElementById("detail-video-url");
    if (task.bili_url) {
        videoUrlLink.href = task.bili_url;
        videoUrlLink.style.display = "inline-flex";
    } else if (task.bvid) {
        videoUrlLink.href = `https://www.bilibili.com/video/${task.bvid}`;
        videoUrlLink.style.display = "inline-flex";
    } else {
        videoUrlLink.href = "#";
        videoUrlLink.style.display = "none";
    }
    
    // 决定初始标签页
    if (defaultMode) {
        currentViewMode = defaultMode;
    } else {
        if (task.result) {
            currentViewMode = "final";
        } else if (task.raw_result) {
            currentViewMode = "raw";
        } else {
            currentViewMode = "raw";
        }
    }
    
    // 启用或禁用标签按钮
    if (task.result) {
        tabBtnFinal.removeAttribute("disabled");
    } else {
        // 如果还没有 final 结果且当前模式被设为了 final，则强行切换到 raw 模式
        tabBtnFinal.setAttribute("disabled", "true");
        if (currentViewMode === "final") {
            currentViewMode = "raw";
        }
    }
    
    if (task.raw_result) {
        tabBtnRaw.removeAttribute("disabled");
    } else {
        tabBtnRaw.setAttribute("disabled", "true");
        if (currentViewMode === "raw") {
            currentViewMode = "final";
        }
    }
    
    // 更新标签的高亮激活状态
    tabBtnFinal.classList.remove("active");
    tabBtnRaw.classList.remove("active");
    
    if (currentViewMode === "final") {
        tabBtnFinal.classList.add("active");
    } else {
        tabBtnRaw.classList.add("active");
    }
    
    // 渲染剧本内容
    renderTranscriptCurrentMode();
    
    // 切换面板到详情
    switchPanel(panelDetail);
}

// 绑定标签切换按钮事件
tabBtnFinal.addEventListener("click", () => {
    if (tabBtnFinal.hasAttribute("disabled")) return;
    currentViewMode = "final";
    tabBtnFinal.classList.add("active");
    tabBtnRaw.classList.remove("active");
    renderTranscriptCurrentMode();
});

tabBtnRaw.addEventListener("click", () => {
    if (tabBtnRaw.hasAttribute("disabled")) return;
    currentViewMode = "raw";
    tabBtnRaw.classList.add("active");
    tabBtnFinal.classList.remove("active");
    renderTranscriptCurrentMode();
});

// 复制全文逻辑
btnCopyAll.addEventListener("click", () => {
    if (!currentTaskData) return;
    
    let sourceData = {};
    let isRawMode = currentViewMode === "raw";
    
    try {
        if (isRawMode) {
            sourceData = typeof currentTaskData.raw_result === "string" 
                ? JSON.parse(currentTaskData.raw_result) 
                : (currentTaskData.raw_result || {});
        } else {
            sourceData = typeof currentTaskData.result === "string" 
                ? JSON.parse(currentTaskData.result) 
                : (currentTaskData.result || {});
        }
    } catch (e) {
        alert("剧本数据格式错误，无法复制");
        return;
    }
    
    let segments = sourceData[currentViewSource] || [];
    
    if (segments.length === 0) {
        alert("没有可复制的内容");
        return;
    }
    
    // 将剧本合并并排版成一段长文本
    let textToCopy = "";
    segments.forEach(seg => {
        const start = seg.start || 0.0;
        const end = seg.end || 0.0;
        const timeStr = `[${formatTime(start)} - ${formatTime(end)}]`;
        if (isRawMode) {
            textToCopy += `${timeStr} 说话人 (草稿): ${seg.text || ""}\n`;
        } else {
            const speakerId = seg.speaker !== undefined ? seg.speaker : 0;
            textToCopy += `${timeStr} 说话人 ${speakerId}: ${seg.text || ""}\n`;
        }
    });
    
    const successCallback = () => {
        const originalText = btnCopyAll.querySelector(".copy-text").innerText;
        btnCopyAll.classList.add("success");
        btnCopyAll.querySelector(".copy-text").innerText = "复制成功！";
        
        setTimeout(() => {
            btnCopyAll.classList.remove("success");
            btnCopyAll.querySelector(".copy-text").innerText = originalText;
        }, 2000);
    };

    const errorCallback = (err) => {
        console.error("复制失败:", err);
        alert("复制失败，请检查浏览器剪贴板权限或手动选择文本复制。");
    };

    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(textToCopy).then(successCallback).catch(errorCallback);
    } else {
        // Fallback for non-HTTPS (e.g., local network IP)
        try {
            const textArea = document.createElement("textarea");
            textArea.value = textToCopy;
            // Move out of screen
            textArea.style.position = "fixed";
            textArea.style.left = "-999999px";
            textArea.style.top = "-999999px";
            document.body.appendChild(textArea);
            textArea.focus();
            textArea.select();
            
            const successful = document.execCommand('copy');
            textArea.remove();
            
            if (successful) {
                successCallback();
            } else {
                errorCallback(new Error("execCommand('copy') failed"));
            }
        } catch (err) {
            errorCallback(err);
        }
    }
});

// 查看详细日志
btnViewLog.addEventListener("click", () => {
    if (!currentTaskData) return;
    // SSE 中包含了详细日志的接口，可直接打开新标签页访问
    const logUrl = `/api/tasks/${currentTaskData.id}/log?token=${authToken}`;
    window.open(logUrl, "_blank");
});

// 重试转录任务按钮点击
btnRetryTask.addEventListener("click", async () => {
    if (!activeTaskId) return;
    
    try {
        btnRetryTask.disabled = true;
        btnRetryTask.querySelector("span").innerText = "正在拉起重试...";
        
        await apiRequest(`/api/tasks/${activeTaskId}/retry`, { method: "POST" });
        
        // 重置界面提示，进入重新排队面板
        btnRetryTask.style.display = "none";
        btnRetryTask.disabled = false;
        btnRetryTask.querySelector("span").innerText = "重试转录任务";
        
        // 重置处理面板显示
        const dummyTask = {
            id: activeTaskId,
            status: "pending",
            title: currentTaskData ? currentTaskData.title : "正在拉起重试...",
            description: "请稍候，任务已重新塞入排队下载队列...",
            bili_url: currentTaskData ? currentTaskData.bili_url : null,
            bvid: currentTaskData ? currentTaskData.bvid : null
        };
        setupProcessingPanel(dummyTask);
        
        // 重新加载列表状态以显示排队中
        fetchTaskList();
        
        // 重新开启进度 SSE 监听
        startProgressListener(activeTaskId);
        
    } catch (err) {
        alert(`拉起重试失败: ${err.message}`);
        btnRetryTask.disabled = false;
        btnRetryTask.querySelector("span").innerText = "重试转录任务";
    }
});

/* ==========================================================================
   7. 启动入口与自运行初始化
   ========================================================================== */

function initApp() {
    fetchTaskList();
    // 如果后台有长连接并且有任务正在进行，恢复连接
    // 此处可做额外工作，我们只做默认列表拉取
}

// 页面首次载入事件
window.addEventListener("load", checkAuth);


