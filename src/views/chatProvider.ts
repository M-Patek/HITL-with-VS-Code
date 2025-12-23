import * as vscode from 'vscode';
import * as crypto from 'crypto'; // [Security Fix] Native crypto
import { ContextManager } from '../managers/contextManager';
import { ActionManager } from '../managers/actionManager';
import { ProcessManager } from '../managers/processManager';

export class ChatViewProvider implements vscode.WebviewViewProvider {

    public static readonly viewType = 'gemini-swarm.chatView';
    private _view?: vscode.WebviewView;
    private _contextManager: ContextManager;
    private _actionManager: ActionManager;

    constructor(
        private readonly _extensionUri: vscode.Uri,
    ) { 
        this._contextManager = new ContextManager();
        this._actionManager = ActionManager.getInstance();
    }

    public resolveWebviewView(
        webviewView: vscode.WebviewView,
        context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken,
    ) {
        this._view = webviewView;
        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this._extensionUri]
        };
        webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);

        webviewView.webview.onDidReceiveMessage(async (data) => {
            // [Security Fix] Trust Boundary Enforcement
            // Always verify intent on Host side for critical actions
            
            switch (data.type) {
                case 'webview_ready': {
                    // [Fix] Get Dynamic Port instead of config
                    const port = ProcessManager.getActivePort();
                    this.sendToWebview('init', { port: port });
                    break;
                }
                case 'get_context': {
                    await this.handleGetContext();
                    break;
                }
                case 'insertCode': {
                    const editor = vscode.window.activeTextEditor;
                    if (editor) {
                        // insertCode is low risk (requires focus), but we could check file match
                        await this._actionManager.insertCode(editor, data.code);
                    }
                    break;
                }
                case 'run_terminal': {
                    // [Security] ActionManager handles confirmation dialog
                    this._actionManager.runInTerminal(data.command);
                    break;
                }
                case 'apply_file_change': {
                    // [Security Fix] Explicit Host Confirmation
                    // Prevent Webview from silently overwriting files via XSS
                    const allowed = await vscode.window.showInformationMessage(
                        `🤖 Gemini Swarm wants to write to file:\n${data.path}`,
                        { modal: true },
                        "Allow Write", "Deny"
                    );

                    if (allowed === "Allow Write") {
                        try {
                            await this._actionManager.applyFileChange(data.path, data.content);
                        } catch (e) {
                             // Error already handled in ActionManager
                        }
                    } else {
                        vscode.window.showWarningMessage("Write operation denied by user.");
                        this.sendToWebview('tool_denied', { id: data.id });
                    }
                    break;
                }
                case 'apply_diff': {
                    // [Security Fix] Explicit Host Confirmation for Diff
                    const allowed = await vscode.window.showInformationMessage(
                        `🤖 Gemini Swarm wants to apply diff to:\n${data.path}`,
                        { modal: true },
                        "Allow Diff", "Deny"
                    );

                    if (allowed === "Allow Diff") {
                        await this._actionManager.applySmartDiff(data.path, data.search_block, data.replace_block);
                    }
                    break;
                }
                case 'view_diff': {
                    await this._actionManager.previewFileDiff(data.path, data.content);
                    break;
                }
                case 'semantic_commit': {
                    vscode.commands.executeCommand('gemini-swarm.semanticCommit', data.message);
                    break;
                }
            }
        });
    }

    public triggerFixFlow(errorMsg: string, errorContext: string) {
        if (this._view) {
            this._view.show?.(true); 
            this.sendToWebview('trigger_fix', {
                error: errorMsg,
                context: errorContext
            });
        }
    }

    public sendToWebview(type: string, data: any) {
        if (this._view) {
            this._view.webview.postMessage({ type: type, ...data });
        }
    }

    private async handleGetContext() {
        try {
            const contextData = await this._contextManager.collectFullContext();
            let workspaceRoot = "";
            if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
                workspaceRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;
            }
            this.sendToWebview('context_response', {
                ...contextData,
                workspace_root: workspaceRoot
            });
        } catch (error: any) {
            this.sendToWebview('context_response', { 
                file_context: null, project_structure: "", diagnostics: "", workspace_root: "" 
            });
        }
    }

    private _getNonce() {
        // [Security Fix] Use crypto for secure nonce
        return crypto.randomBytes(16).toString('base64');
    }

    private _getHtmlForWebview(webview: vscode.Webview) {
        const nonce = this._getNonce();

        // Use vue.global.prod.js (Assuming user has it locally as per README)
        const vueUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'media', 'vue.global.prod.js'));
        const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'media', 'main.js'));
        const stylesUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'media', 'styles.css'));

        // [Security Fix] CSP
        // Removed 'unsafe-eval' to prevent RCE via Webview. 
        // Note: This requires using Vue Runtime-only build or pre-compiled templates if using 'vue.global.prod.js'.
        // If 'vue.global.prod.js' includes the compiler, it might warn about CSP.
        // For strict security, we keep unsafe-eval blocked.
        
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}'; connect-src 'self' http://127.0.0.1:*;">
    <link href="${stylesUri}" rel="stylesheet">
    <script nonce="${nonce}" src="${vueUri}"></script>
    <title>Gemini Swarm Mission Control</title>
</head>
<body>
    <div id="app">
        <header class="hud-header">
            <div class="status-group">
                <div class="status-item" :class="{ active: serverPort }">
                    <span class="status-dot"></span>
                    <span class="status-label">ENGINE: {{ serverPort || 'OFF' }}</span>
                </div>
                <div class="status-item" :class="{ active: isSandboxActive }">
                    <span class="icon">📦</span>
                    <span class="status-label">{{ isSandboxActive ? 'DOCKER' : 'MOCK' }}</span>
                </div>
            </div>
            
            <div class="mode-select-container">
                <select v-model="selectedMode" class="mode-select" title="Agent Mode">
                    <option value="coder">👨‍💻 Coder</option>
                    <option value="architect">🏗️ Architect</option>
                    <option value="debugger">🐞 Debugger</option>
                </select>
            </div>

            <div class="cost-group" v-if="costStats.totalTokens > 0">
                <span class="cost-value">\${{ costStats.totalCost.toFixed(4) }}</span>
                <span class="cost-label">USD</span>
            </div>
        </header>

        <main id="chat-container" ref="chatContainer">
            <div v-if="messages.length === 0" class="welcome-screen">
                <div class="logo">🐱</div>
                <h2>Gemini Swarm</h2>
                <p>Mode: <b>{{ selectedMode.toUpperCase() }}</b></p>
                <div class="capabilities">
                    <span>⚡ Slash Commands: /fix, /test</span>
                    <span>👻 Ghost Text Active</span>
                </div>
            </div>

            <div v-for="(msg, idx) in messages" :key="idx" :class="['message-row', msg.role]">
                <div class="avatar" :title="msg.role">
                    <span v-if="msg.role === 'user'">👤</span>
                    <span v-else-if="msg.role === 'ai'">🤖</span>
                    <span v-else>⚙️</span>
                </div>

                <div class="message-content">
                    <div v-if="msg.type !== 'code' && msg.type !== 'tool_proposal' && msg.type !== 'image' && msg.type !== 'commit_proposal'" class="bubble">
                        <div v-if="msg.role === 'system'" class="system-prefix">[SYSTEM]</div>
                        {{ msg.content }}
                    </div>

                    <div v-else-if="msg.type === 'image'" class="artifact-card image-card">
                        <div class="artifact-header">
                            <span>📊 Generated Image</span>
                        </div>
                        <div class="image-wrapper">
                            <img :src="msg.content" alt="Generated Plot" />
                        </div>
                    </div>

                    <div v-else-if="msg.type === 'code'" class="artifact-card code-card">
                        <div class="artifact-header">
                            <span>📝 Generated Code</span>
                            <div class="actions">
                                <button class="icon-btn" @click="insertCode(msg.content)" title="Insert at Cursor">📥 Insert</button>
                            </div>
                        </div>
                        <pre class="code-preview"><code>{{ msg.content }}</code></pre>
                    </div>

                    <div v-else-if="msg.type === 'commit_proposal'" class="artifact-card tool-card approved">
                        <div class="tool-header">
                            <span class="tool-icon">💾</span>
                            <span class="tool-name">Auto Commit</span>
                        </div>
                        <div class="tool-body">
                            <code>{{ msg.content }}</code>
                        </div>
                        <div class="tool-actions">
                            <button class="btn approve" @click="doSemanticCommit(msg.content)">✅ Commit</button>
                        </div>
                    </div>

                    <div v-else-if="msg.type === 'tool_proposal'" class="artifact-card tool-card" :class="{ approved: msg.approved, rejected: msg.rejected }">
                        <div class="tool-header">
                            <span class="tool-icon" v-if="msg.content.tool === 'write_to_file'">💾</span>
                            <span class="tool-icon" v-else-if="msg.content.tool === 'apply_diff'">📝</span>
                            <span class="tool-icon" v-else>⚡</span>
                            <span class="tool-name">{{ msg.label || msg.content.tool }}</span>
                        </div>
                        
                        <div class="tool-body">
                            <div v-if="msg.content.tool === 'write_to_file' || msg.content.tool === 'apply_diff'">
                                <div class="param-row">
                                    <span class="label">PATH:</span>
                                    <span class="value path">{{ msg.content.params.path }}</span>
                                </div>
                            </div>
                            <div v-else-if="msg.content.tool === 'execute_command'">
                                <div class="param-row">
                                    <span class="label">CMD:</span>
                                    <code class="value command">{{ msg.content.params.command }}</code>
                                </div>
                            </div>
                        </div>

                        <div class="tool-actions" v-if="!msg.approved && !msg.rejected">
                            <button v-if="msg.content.tool === 'write_to_file' || msg.content.tool === 'apply_diff'" class="btn secondary" @click="viewDiff(msg.content)">
                                👁️ View Diff
                            </button>
                            <div class="approval-group">
                                <button class="btn reject" @click="rejectTool(idx)">🚫 Reject</button>
                                <button class="btn approve" @click="approveTool(idx, msg.content)">✅ Approve</button>
                            </div>
                        </div>
                        <div class="status-stamp approved" v-if="msg.approved">APPROVED</div>
                        <div class="status-stamp rejected" v-if="msg.rejected">REJECTED</div>
                    </div>

                </div>
            </div>

            <div v-if="isProcessing" class="thinking-row">
                <div class="spinner"></div>
                <span>Coding Crew is working...</span>
            </div>
        </main>

        <footer class="input-deck">
            <div class="toolbar">
                <button class="tool-btn" @click="runTest" title="Run Terminal Test">💻</button>
                <span class="spacer"></span>
                <span class="token-counter" v-if="costStats.totalTokens">{{ formatNumber(costStats.totalTokens) }} toks</span>
            </div>
            <div class="input-wrapper">
                <textarea 
                    v-model="userInput" 
                    @keydown.enter.prevent="startTask" 
                    placeholder="Type '/' for commands (e.g. /fix, /test)..." 
                    rows="1"
                    ref="inputBox"
                ></textarea>
                <button class="send-btn" @click="startTask" :disabled="isProcessing || !userInput">
                    🚀
                </button>
            </div>
        </footer>
    </div>
    <script nonce="${nonce}" src="${scriptUri}"></script>
    <style>
        .mode-select-container { margin-left: 10px; }
        .mode-select {
            background: var(--vscode-dropdown-background);
            color: var(--vscode-dropdown-foreground);
            border: 1px solid var(--vscode-dropdown-border);
            padding: 2px 4px;
            border-radius: 3px;
            font-size: 0.8em;
        }
    </style>
</body>
</html>`;
    }
}
