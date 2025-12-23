const { createApp, ref, nextTick, onMounted, watch } = Vue;

const app = createApp({
    setup() {
        const vscode = acquireVsCodeApi();
        
        // --- State Management ---
        const oldState = vscode.getState() || { messages: [], serverPort: 8000 };
        const messages = ref(oldState.messages || []);
        const userInput = ref('');
        const isProcessing = ref(false);
        const serverPort = ref(oldState.serverPort || 8000); 
        const currentTaskId = ref(null);
        const chatContainer = ref(null);
        let contextResolver = null;

        // [Roo Code] Cost Dashboard State
        const costStats = ref({
            totalCost: 0.0,
            totalTokens: 0,
            requests: 0
        });

        // --- Persistence ---
        watch([messages, serverPort], () => {
            vscode.setState({
                messages: messages.value,
                serverPort: serverPort.value
            });
        }, { deep: true });

        // --- Initialization ---
        onMounted(() => {
            window.addEventListener('message', event => {
                const message = event.data;
                switch (message.type) {
                    case 'init':
                        serverPort.value = message.port;
                        if (messages.value.length === 0) {
                            addSystemMessage(`🔌 Engine Connected on Port ${serverPort.value}`);
                        }
                        break;
                    case 'context_response':
                        if (contextResolver) {
                            contextResolver(message);
                            contextResolver = null;
                        }
                        break;
                    case 'trigger_fix': 
                        handleTriggerFix(message.error, message.context);
                        break;
                }
            });
            // Signal VS Code that webview is ready to receive port config
            vscode.postMessage({ type: 'webview_ready' });
            scrollToBottom();
        });

        // --- Helpers ---
        const addSystemMessage = (text) => {
            messages.value.push({ role: 'system', content: text });
            scrollToBottom();
        };

        const scrollToBottom = () => {
            nextTick(() => {
                if (chatContainer.value) {
                    chatContainer.value.scrollTop = chatContainer.value.scrollHeight;
                }
            });
        };

        const formatNumber = (num) => {
            if (!num) return "0";
            return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        };

        // --- Actions ---
        const handleTriggerFix = (errorMsg, errorCtx) => {
            const fixPrompt = `Please fix the following error:\n"${errorMsg}"\n\nCode Context:\n${errorCtx}`;
            userInput.value = fixPrompt;
        };

        const fetchContextFromVSCode = () => {
            return new Promise((resolve) => {
                contextResolver = resolve;
                vscode.postMessage({ type: 'get_context' });
                // Timeout safety
                setTimeout(() => {
                    if (contextResolver) {
                        resolve({ file_context: null, project_structure: "", diagnostics: "", workspace_root: null });
                        contextResolver = null;
                        addSystemMessage("⚠️ Context collection timed out.");
                    }
                }, 10000);
            });
        };

        const insertCode = (code) => {
            vscode.postMessage({ type: 'insertCode', code: code });
        };

        const runTest = () => {
            vscode.postMessage({ type: 'run_terminal', command: 'echo "Hello from Gemini Terminal!"' });
        };

        // --- Roo Code / Tool Approval Logic ---
        const approveTool = (msgIdx, toolData) => {
            // Mark as approved in UI
            messages.value[msgIdx].approved = true;
            
            // Send instruction to VS Code Extension
            if (toolData.tool === 'write_to_file') {
                vscode.postMessage({ 
                    type: 'apply_file_change', 
                    path: toolData.params.path,
                    content: toolData.params.content
                });
            } else if (toolData.tool === 'execute_command') {
                vscode.postMessage({ 
                    type: 'run_terminal', 
                    command: toolData.params.command
                });
            }
        };

        const rejectTool = (msgIdx) => {
            messages.value[msgIdx].rejected = true;
        };

        const viewDiff = (toolData) => {
            if (toolData.tool === 'write_to_file') {
                vscode.postMessage({ 
                    type: 'view_diff', 
                    path: toolData.params.path,
                    content: toolData.params.content
                });
            }
        };

        // --- Core Task Logic ---
        const startTask = async () => {
            if (!userInput.value.trim() || isProcessing.value) return;

            const text = userInput.value;
            userInput.value = '';
            messages.value.push({ role: 'user', content: text });
            isProcessing.value = true;
            scrollToBottom();

            try {
                addSystemMessage("👁️ Scanning workspace & Generating Map...");
                const contextData = await fetchContextFromVSCode();
                
                let finalInput = text;
                if (contextData.diagnostics) {
                    finalInput += `\n\n[System Detected Errors]:\n${contextData.diagnostics}`;
                }

                const payload = { 
                    user_input: finalInput,
                    thread_id: `vscode_${Date.now()}`,
                    file_context: contextData.file_context,
                    workspace_root: contextData.workspace_root
                };

                const response = await fetch(`http://127.0.0.1:${serverPort.value}/api/start_task`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (!response.ok) throw new Error('API Request Failed');
                const data = await response.json();
                currentTaskId.value = data.task_id;
                
                // Start SSE Stream
                connectSSE(data.task_id);

            } catch (e) {
                addSystemMessage(`❌ Error: ${e.message}`);
                isProcessing.value = false;
            }
        };

        // --- SSE Stream Handler ---
        const connectSSE = (taskId) => {
            const url = `http://127.0.0.1:${serverPort.value}/api/stream/${taskId}`;
            const evtSource = new EventSource(url);

            // 1. Code Generated (Legacy & Fallback)
            evtSource.addEventListener('code_generated', (e) => {
                const data = JSON.parse(e.data);
                messages.value.push({
                    role: 'ai',
                    type: 'code',
                    content: data.content,
                    label: 'Generated Code'
                });
                scrollToBottom();
            });

            // 2. Tool Proposal (Roo Code)
            evtSource.addEventListener('tool_proposal', (e) => {
                const data = JSON.parse(e.data);
                messages.value.push({
                    role: 'ai',
                    type: 'tool_proposal',
                    content: data,
                    label: `Tool Request: ${data.tool}`
                });
                scrollToBottom();
            });

            // 3. Image Generated (Sandbox)
            evtSource.addEventListener('image_generated', (e) => {
                const data = JSON.parse(e.data);
                if (data.images && data.images.length > 0) {
                    data.images.forEach(img => {
                        messages.value.push({
                            role: 'ai',
                            type: 'image',
                            content: img.data,
                            label: img.filename || 'Generated Image'
                        });
                    });
                    scrollToBottom();
                }
            });

            // 4. Usage Update (Cost Dashboard)
            evtSource.addEventListener('usage_update', (e) => {
                const data = JSON.parse(e.data);
                costStats.value = {
                    totalCost: data.total_cost,
                    totalTokens: data.total_tokens,
                    requests: data.requests
                };
            });
            
            // 5. Errors
            evtSource.addEventListener('error', (e) => {
                try {
                    const err = JSON.parse(e.data);
                    addSystemMessage(`⚠️ Engine Error: ${err}`);
                } catch {}
            });

            // 6. Finish
            evtSource.addEventListener('finish', () => {
                evtSource.close();
                isProcessing.value = false;
                addSystemMessage('✅ Task Completed');
            });
            
            evtSource.onerror = (err) => {
                evtSource.close();
                isProcessing.value = false;
            };
        };

        return {
            messages, userInput, isProcessing, chatContainer,
            costStats, formatNumber,
            startTask, insertCode, runTest,
            approveTool, rejectTool, viewDiff
        };
    }
});

app.mount('#app');
