const { createApp, ref, nextTick, onMounted, watch } = Vue;

const app = createApp({
    setup() {
        const vscode = acquireVsCodeApi();
        
        const oldState = vscode.getState() || { messages: [], serverPort: 0, activeTaskId: null, mode: 'coder' };
        const messages = ref(oldState.messages || []);
        const userInput = ref('');
        const isProcessing = ref(false);
        const serverPort = ref(oldState.serverPort || 0); 
        const isSandboxActive = ref(true);
        const activeTaskId = ref(oldState.activeTaskId || null);
        const selectedMode = ref(oldState.mode || 'coder'); // [Phase 3] Mode
        const chatContainer = ref(null);
        let contextResolver = null;
        const costStats = ref({ totalCost: 0.0, totalTokens: 0, requests: 0 });

        watch([messages, serverPort, activeTaskId, selectedMode], () => {
            vscode.setState({
                messages: messages.value,
                serverPort: serverPort.value,
                activeTaskId: activeTaskId.value,
                mode: selectedMode.value
            });
        }, { deep: true });

        onMounted(() => {
            window.addEventListener('message', event => {
                const message = event.data;
                switch (message.type) {
                    case 'init':
                        serverPort.value = message.port;
                        if (activeTaskId.value && serverPort.value) {
                            connectSSE(activeTaskId.value);
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

        const scrollToBottom = () => {
            nextTick(() => {
                if (chatContainer.value) {
                    chatContainer.value.scrollTop = chatContainer.value.scrollHeight;
                }
            });
        };

        const formatNumber = (num) => num ? num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",") : "0";

        const handleTriggerFix = (errorMsg, errorCtx) => {
            userInput.value = `/fix ${errorMsg}\n\nContext:\n${errorCtx}`;
        };

        const insertCode = (code) => vscode.postMessage({ type: 'insertCode', code: code });
        const runTest = () => vscode.postMessage({ type: 'run_terminal', command: 'echo "Gemini Swarm Test"' });
        
        // [Phase 3] Semantic Commit Trigger
        const doSemanticCommit = (msg) => {
             vscode.postMessage({ type: 'semantic_commit', message: msg });
        };
        
        const viewDiff = (toolData) => {
            if (toolData.tool === 'write_to_file' || toolData.tool === 'apply_diff') {
                // If it's apply_diff, we might need to construct the full content first to view diff
                // For now, let's assume ActionManager handles simple diff view or we pass raw params
                // But ActionManager expects 'content' for previewFileDiff.
                // If apply_diff, we might just show the search/replace block in a text doc?
                // Simplification: For apply_diff, just show the replace_block as "New Content Proposal" 
                // (Though strictly incorrect, it allows viewing what AI wrote)
                let content = toolData.params.content;
                if (toolData.tool === 'apply_diff') {
                    content = `<<<< SEARCH\n${toolData.params.search_block}\n====\n${toolData.params.replace_block}\n>>>> REPLACE`;
                }
                vscode.postMessage({ 
                    type: 'view_diff', 
                    path: toolData.params.path,
                    content: content
                });
            }
        };

        const approveTool = (msgIdx, toolData) => {
            messages.value[msgIdx].approved = true;
            if (toolData.tool === 'write_to_file') {
                vscode.postMessage({ type: 'apply_file_change', path: toolData.params.path, content: toolData.params.content });
            } else if (toolData.tool === 'apply_diff') {
                vscode.postMessage({ 
                    type: 'apply_diff', 
                    path: toolData.params.path, 
                    search_block: toolData.params.search_block,
                    replace_block: toolData.params.replace_block 
                });
            } else if (toolData.tool === 'execute_command') {
                vscode.postMessage({ type: 'run_terminal', command: toolData.params.command });
            }
        };

        const rejectTool = (msgIdx) => messages.value[msgIdx].rejected = true;

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

        const startTask = async () => {
            if (!userInput.value.trim() || isProcessing.value) return;

            let text = userInput.value.trim();
            // [Phase 3] Slash Command Parsing (Simple)
            let currentMode = selectedMode.value;
            
            if (text.startsWith('/fix')) {
                currentMode = 'debugger';
                text = text.replace('/fix', '').trim();
                if (!text) text = "Fix the errors in the current file.";
            } else if (text.startsWith('/test')) {
                text = "Write unit tests for the current code. " + text.replace('/test', '').trim();
            }

            userInput.value = '';
            messages.value.push({ role: 'user', content: text, type: 'text' });
            isProcessing.value = true;
            scrollToBottom();

            try {
                const contextData = await fetchContextFromVSCode();
                let finalInput = text;
                if (contextData.diagnostics && currentMode === 'debugger') {
                    finalInput += `\n\n[Active Diagnostics]:\n${contextData.diagnostics}`;
                }

                const payload = { 
                    user_input: finalInput,
                    thread_id: `vscode_${Date.now()}`,
                    file_context: contextData.file_context,
                    workspace_root: contextData.workspace_root,
                    mode: currentMode // [Phase 3] Send Mode
                };

                const response = await fetch(`http://127.0.0.1:${serverPort.value}/api/start_task`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (!response.ok) throw new Error('API Request Failed');
                const data = await response.json();
                
                activeTaskId.value = data.task_id;
                connectSSE(data.task_id);

            } catch (e) {
                messages.value.push({ role: 'system', content: `❌ Error: ${e.message}`, type: 'text' });
                isProcessing.value = false;
            }
        };

        const connectSSE = (taskId) => {
            isProcessing.value = true;
            const url = `http://127.0.0.1:${serverPort.value}/api/stream/${taskId}`;
            const evtSource = new EventSource(url);

            const handleEvent = (data, type, label) => {
                 messages.value.push({ role: 'ai', type: type, content: data, label: label });
                 scrollToBottom();
            };

            evtSource.addEventListener('code_generated', (e) => handleEvent(JSON.parse(e.data).content, 'code', 'Code'));
            
            evtSource.addEventListener('tool_proposal', (e) => {
                const d = JSON.parse(e.data);
                handleEvent(d, 'tool_proposal', `Request: ${d.tool}`);
            });
            
            // [Phase 3] Commit Proposal
            evtSource.addEventListener('commit_proposal', (e) => {
                handleEvent(e.data, 'commit_proposal', 'Commit');
            });

            evtSource.addEventListener('image_generated', (e) => {
                const d = JSON.parse(e.data);
                if (d.images) d.images.forEach(img => handleEvent(img.data, 'image', img.filename));
            });

            evtSource.addEventListener('usage_update', (e) => costStats.value = JSON.parse(e.data));
            
            evtSource.addEventListener('finish', () => {
                evtSource.close();
                isProcessing.value = false;
                activeTaskId.value = null;
            });
            
            evtSource.onerror = () => {
                evtSource.close();
                isProcessing.value = false;
            };
        };

        return {
            messages, userInput, isProcessing, chatContainer, costStats,
            serverPort, isSandboxActive, formatNumber, selectedMode,
            startTask, insertCode, runTest, approveTool, rejectTool, viewDiff, doSemanticCommit
        };
    }
});

app.mount('#app');
