import * as vscode from 'vscode';
import { ContextManager } from '../managers/contextManager';
import { ActionManager } from '../managers/actionManager';

export class ChatViewProvider implements vscode.WebviewViewProvider {

    public static readonly viewType = 'gemini-swarm.chatView';
    private _view?: vscode.WebviewView;
    private _contextManager: ContextManager;
    private _actionManager: ActionManager;

    constructor(
        private readonly _extensionUri: vscode.Uri,
    ) { 
        this._contextManager = new ContextManager();
        this._actionManager = new ActionManager();
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
            switch (data.type) {
                case 'webview_ready': {
                    const config = vscode.workspace.getConfiguration('geminiSwarm');
                    const port = config.get<number>('serverPort') || 8000;
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
                        await this._actionManager.insertCode(editor, data.code);
                    } else {
                        vscode.window.showErrorMessage('❌ No active editor found!');
                    }
                    break;
                }
                case 'run_terminal': {
                    this._actionManager.runInTerminal(data.command);
                    break;
                }
                case 'apply_file_change': {
                    await this._actionManager.applyFileChange(data.path, data.content);
                    break;
                }
                case 'view_diff': { // [Roo Code] Handle Diff Request
                    await this._actionManager.previewFileDiff(data.path, data.content);
                    break;
                }
                case 'onInfo': {
                    vscode.window.showInformationMessage(data.value);
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
            console.error('Context collection failed:', error);
            this.sendToWebview('context_response', { 
                file_context: null, 
                project_structure: "", 
                diagnostics: "",
                workspace_root: "" 
            });
        }
    }

    private _getHtmlForWebview(webview: vscode.Webview) {
        const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'media', 'main.js'));
        const stylesUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'media', 'styles.css'));
        
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src ${webview.cspSource} 'unsafe-eval' https://unpkg.com; connect-src 'self' http://127.0.0.1:*;">
    <link href="${stylesUri}" rel="stylesheet">
    <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
    <title>Gemini Swarm</title>
</head>
<body>
    <div id="app">
        <div id="chat-container" ref="chatContainer">
            <div v-if="messages.length === 0" class="message system">
                🐱 <b>Gemini Swarm Engine (Roo Code Style)</b><br>
                <span>Ready to Code.</span>
            </div>
            
            <div v-for="(msg, idx) in messages" :key="idx" :class="['message', msg.role]">
                
                <div v-if="msg.type !== 'code' && msg.type !== 'tool_proposal'">{{ msg.content }}</div>

                <div v-else-if="msg.type === 'code'" class="artifact-card">
                    <div class="artifact-header">
                        <span>CODE SNIPPET</span>
                        <div class="actions">
                            <button class="icon-btn" @click="insertCode(msg.content)">INSERT 📥</button>
                        </div>
                    </div>
                    <div class="artifact-content">{{ msg.content }}</div>
                </div>

                <!-- Tool Proposal Card -->
                <div v-else-if="msg.type === 'tool_proposal'" class="artifact-card tool-card">
                    <div class="artifact-header tool-header">
                        <span>🛠️ {{ msg.label }}</span>
                    </div>
                    <div class="artifact-content">
                        <div v-if="msg.content.tool === 'write_to_file'">
                            <strong>Path:</strong> {{ msg.content.params.path }}<br>
                            <pre class="code-preview">{{ msg.content.params.content.slice(0, 150) }}...</pre>
                        </div>
                        <div v-if="msg.content.tool === 'execute_command'">
                            <strong>Command:</strong> <code>{{ msg.content.params.command }}</code>
                        </div>
                    </div>
                    
                    <div class="tool-actions" v-if="!msg.approved && !msg.rejected">
                        <!-- [Roo Code] View Diff Button -->
                        <button v-if="msg.content.tool === 'write_to_file'" class="diff-btn" @click="viewDiff(msg.content)">
                            👀 View Diff
                        </button>
                        
                        <button class="approve-btn" @click="approveTool(idx, msg.content)">
                            ✅ Approve
                        </button>
                        <button class="reject-btn" @click="rejectTool(idx)">
                            ❌ Reject
                        </button>
                    </div>
                    
                    <div class="tool-status" v-if="msg.approved">
                        ✅ Approved & Executed
                    </div>
                    <div class="tool-status" v-if="msg.rejected">
                        ❌ Rejected
                    </div>
                </div>

            </div>

            <div v-if="isProcessing" class="message system">
                <span>Thinking... <span class="loading-dots">...</span></span>
            </div>
        </div>

        <div id="input-area">
            <textarea v-model="userInput" @keydown.enter.prevent="startTask" placeholder="Ask Coding Crew..." rows="3" :disabled="isProcessing"></textarea>
            <button @click="startTask" :disabled="isProcessing || !userInput">{{ isProcessing ? 'Processing...' : 'Send 🚀' }}</button>
        </div>
    </div>
    <script src="${scriptUri}"></script>
</body>
</html>`;
    }
}
