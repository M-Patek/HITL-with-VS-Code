const { createApp, ref, nextTick, onMounted, watch } = Vue;

const app = createApp({
    setup() {
        const vscode = acquireVsCodeApi();
        
        // [New] State Persistence Logic
        const oldState = vscode.getState() || { messages: [], serverPort: 8000 };

        // State
        const messages = ref(oldState.messages || []);
        const userInput = ref('');
        const isProcessing = ref(false);
        const serverPort = ref(oldState.serverPort || 8000); 
        const currentTaskId = ref(null);
        const chatContainer = ref(null);
        let contextResolver = null;

        // [New] Watch state changes and save
        watch([messages, serverPort], () => {
            vscode.setState({
                messages: messages.value,
                serverPort: serverPort.value
            });
        }, { deep: true });

        onMounted(() => {
            window.addEventListener('message', event => {
                const message = event.data;
                switch (message.type) {
                    case 'init':
                        serverPort.value = message.port;
                        // Don't clear history on init, just append info
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
            vscode.postMessage({ type: 'webview_ready' });
            scrollToBottom();
        });

        // Methods
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

        const handleTriggerFix = (errorMsg, errorCtx) => {
            const fixPrompt = `Please fix the following error:\n"${errorMsg}"\n\nCode Context:\n${errorCtx}`;
            userInput.value = fixPrompt;
            // startTask(); // Let user confirm before sending
        };

        const fetchContextFromVSCode = () => {
            return new Promise((resolve) => {
                contextResolver = resolve;
                vscode.postMessage({ type: 'get_context' });
                // [Optimization] 增加超时时间到 10s，防止大型项目超时
                setTimeout(() => {
                    if (contextResolver) {
                        resolve({ file_context: null, project_structure: "", diagnostics: "" });
                        contextResolver = null;
                        addSystemMessage("⚠️ Context collection timed out (10s).");
                    }
                }, 10000);
            });
        };

        const startTask = async () => {
            if (!userInput.value.trim() || isProcessing.value) return;

            const text = userInput.value;
            userInput.value = '';
            messages.value.push({ role: 'user', content: text });
            isProcessing.value = true;
            scrollToBottom();

            try {
                addSystemMessage("👁️ Scanning workspace context...");
                const contextData = await fetchContextFromVSCode();
                
                let finalInput = text;
                if (contextData.diagnostics) {
                    finalInput += `\n\n[System Detected Errors]:\n${contextData.diagnostics}`;
                }

                const payload = { 
                    user_input: finalInput,
                    thread_id: `vscode_${Date.now()}`,
                    file_context: contextData.file_context,
                    project_structure: contextData.project_structure
                };

                const response = await fetch(`http://127.0.0.1:${serverPort.value}/api/start_task`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (!response.ok) throw new Error('API Request Failed');
                const data = await response.json();
                currentTaskId.value = data.task_id;
                
                connectSSE(data.task_id);

            } catch (e) {
                addSystemMessage(`❌ Error: ${e.message}`);
                isProcessing.value = false;
            }
        };

        const connectSSE = (taskId) => {
            const url = `http://127.0.0.1:${serverPort.value}/api/stream/${taskId}`;
            const evtSource = new EventSource(url);

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

            evtSource.addEventListener('image_generated', (e) => {
                const data = JSON.parse(e.data);
                if (data.images && data.images.length > 0) {
                    data.images.forEach(img => {
                        messages.value.push({
                            role: 'ai',
                            type: 'image',
                            content: img.data, // base64 string
                            label: img.filename || 'Generated Image'
                        });
                    });
                    scrollToBottom();
                }
            });
            
            evtSource.addEventListener('error', (e) => {
                try {
                    const err = JSON.parse(e.data);
                    addSystemMessage(`⚠️ Engine Error: ${err}`);
                } catch {
                     // EventSource error event doesn't always have data
                     // addSystemMessage(`⚠️ Connection Error`);
                }
            });

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

        const insertCode = (code) => {
            vscode.postMessage({ type: 'insertCode', code: code });
        };

        const runTest = () => {
            vscode.postMessage({ type: 'run_terminal', command: 'echo "Hello from Gemini Terminal!"' });
        };

        return {
            messages, userInput, isProcessing, chatContainer,
            startTask, insertCode, runTest
        };
    }
});

app.mount('#app');
