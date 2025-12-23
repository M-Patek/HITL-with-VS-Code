import * as vscode from 'vscode';
import { ContextManager } from '../managers/contextManager';
import { ActionManager } from '../managers/actionManager'; // [New]

export class ChatViewProvider implements vscode.WebviewViewProvider {

    public static readonly viewType = 'gemini-swarm.chatView';
    private _view?: vscode.WebviewView;
    private _contextManager: ContextManager;
    private _actionManager: ActionManager; // [New]

    constructor(
        private readonly _extensionUri: vscode.Uri,
    ) { 
        this._contextManager = new ContextManager();
        this._actionManager = new ActionManager(); // [New]
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
                    // [Refactor] 使用 ActionManager
                    const editor = vscode.window.activeTextEditor;
                    if (editor) {
                        await this._actionManager.insertCode(editor, data.code);
                    } else {
                        vscode.window.showErrorMessage('❌ No active editor found!');
                    }
                    break;
                }
                case 'run_terminal': { // [New] 前端请求执行命令
                    this._actionManager.runInTerminal(data.command);
                    break;
                }
                case 'onInfo': {
                    vscode.window.showInformationMessage(data.value);
                    break;
                }
            }
        });
    }

    /**
     * 外部触发修复流程 (由 QuickFix 调用)
     */
    public triggerFixFlow(errorMsg: string, errorContext: string) {
        if (this._view) {
            this._view.show?.(true); // 激活侧边栏
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
            this.sendToWebview('context_response', contextData);
        } catch (error: any) {
            console.error('Context collection failed:', error);
            this.sendToWebview('context_response', { 
                file_context: null, project_structure: "", diagnostics: "" 
            });
        }
    }

    private _getHtmlForWebview(webview: vscode.Webview) {
        // ... (HTML 生成逻辑保持不变，只需确保引入了 media/main.js)
        const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'media', 'main.js'));
        const stylesUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'media', 'styles.css'));
        // (为节省篇幅，此处省略重复的 HTML 模板字符串，内容同上一阶段)
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
                🐱 <b>Gemini Swarm Engine</b><br>
                <span>Ready to Code.</span>
            </div>
            <div v-for="(msg, idx) in messages" :key="idx" :class="['message', msg.role]">
                <div v-if="msg.type !== 'code'">{{ msg.content }}</div>
                <div v-else class="artifact-card">
                    <div class="artifact-header">
                        <span>CODE GENERATED</span>
                        <div class="actions">
                            <button class="icon-btn" @click="insertCode(msg.content)">INSERT 📥</button>
                            <!-- [New] 未来可扩展 Diff 按钮 -->
                        </div>
                    </div>
                    <div class="artifact-content">{{ msg.content }}</div>
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
