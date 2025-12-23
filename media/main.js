const { createApp, ref, nextTick, onMounted, watch } = Vue;

const app = createApp({
    setup() {
        const vscode = acquireVsCodeApi();
        
        // --- State ---
        const oldState = vscode.getState() || { messages: [], serverPort: 0 };
        const messages = ref(oldState.messages || []);
        const userInput = ref('');
        const isProcessing = ref(false);
        const serverPort = ref(oldState.serverPort || 0); 
        const isSandboxActive = ref(true); // Default to true, update via msg
        const chatContainer = ref(null);
        let contextResolver = null;

        // Cost Dashboard
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

        // --- Lifecycle ---
        onMounted(() => {
            window.addEventListener('message', event => {
                const message = event.data;
                switch (message.type) {
                    case 'init':
                        serverPort.value = message.port;
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
            vscode.postMessage({ type: 'webview_ready' });
            scrollToBottom();
        });

        // --- Helpers ---
        const addSystemMessage = (text) => {
            messages.value.push({ role: 'system', content: text, type: 'text' });
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

        // --- Core Interactions ---
        const handleTriggerFix = (errorMsg, errorCtx) => {
            userInput.value = `Fix this error:\n"${errorMsg}"`;
            startTask(); // Auto-start optionally? Let's just fill input for now
        };

        const insertCode = (code) => {
            vscode.postMessage({ type: 'insertCode', code: code });
        };

        const runTest = () => {
            vscode.postMessage({ type: 'run_terminal', command: 'echo "Gemini Swarm Connection Test 🐱"' });
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

        const approveTool = (msgIdx, toolData) => {
            messages.value[msgIdx].approved = true;
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

        const fetchContextFromVSCode = () => {
            return new Promise((resolve) => {
                contextResolver = resolve;
                vscode.postMessage({ type: 'get_context' });
                setTimeout(() => {
                    if (contextResolver) {
                        resolve({ file_context: null, project_structure: "", diagnostics: "", workspace_root: null });
                        contextResolver = null;
                    }
                }, 5000);
            });
        };

        // --- Task Logic ---
        const startTask = async () => {
            if (!userInput.value.trim() || isProcessing.value) return;

            const text = userInput.value;
            userInput.value = '';
            messages.value.push({ role: 'user', content: text, type: 'text' });
            isProcessing.value = true;
            scrollToBottom();

            try {
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
                
                connectSSE(data.task_id);

            } catch (e) {
                addSystemMessage(`❌ Error: ${e.message}`);
                isProcessing.value = false;
            }
        };

        const connectSSE = (taskId) => {
            const url = `http://127.0.0.1:${serverPort.value}/api/stream/${taskId}`;
            const evtSource = new EventSource(url);

            const handleEvent = (data, type, label) => {
                 messages.value.push({
                    role: 'ai',
                    type: type,
                    content: data,
                    label: label
                });
                scrollToBottom();
            };

            evtSource.addEventListener('code_generated', (e) => {
                handleEvent(JSON.parse(e.data).content, 'code', 'Generated Code');
            });

            evtSource.addEventListener('tool_proposal', (e) => {
                const d = JSON.parse(e.data);
                handleEvent(d, 'tool_proposal', `Request: ${d.tool}`);
            });

            evtSource.addEventListener('image_generated', (e) => {
                const d = JSON.parse(e.data);
                if (d.images) {
                    d.images.forEach(img => {
                        handleEvent(img.data, 'image', img.filename);
                    });
                }
            });

            evtSource.addEventListener('usage_update', (e) => {
                const data = JSON.parse(e.data);
                costStats.value = data;
            });
            
            evtSource.addEventListener('finish', () => {
                evtSource.close();
                isProcessing.value = false;
            });
            
            evtSource.onerror = () => {
                evtSource.close();
                isProcessing.value = false;
            };
        };

        return {
            messages, userInput, isProcessing, chatContainer, costStats,
            serverPort, isSandboxActive, formatNumber,
            startTask, insertCode, runTest, approveTool, rejectTool, viewDiff
        };
    }
});

app.mount('#app');
