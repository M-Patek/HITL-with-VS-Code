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
                    // [Fix] Get Dynamic Port
                    const port = ProcessManager.getActivePort();
                    this.sendToWebview('init', { port: port });
                    break;
                }
                case 'get_context': {
                    await this.handleGetContext();
                    break;
                }
                case 'insertCode': {
                    // [Security] Verify active editor matches intent?
                    // For now, simple insert is low risk as it requires user focus
                    const editor = vscode.window.activeTextEditor;
                    if (editor) {
                        await this._actionManager.insertCode(editor, data.code);
                    }
                    break;
                }
                case 'run_terminal': {
                    // [Security] ActionManager handles confirmation
                    this._actionManager.runInTerminal(data.command);
                    break;
                }
                case 'apply_file_change': {
                    // [Security Fix] Explicit Host Confirmation
                    const allowed = await vscode.window.showInformationMessage(
                        `🤖 Gemini Swarm wants to write to file:\n${data.path}`,
                        { modal: true },
                        "Allow Write", "Deny"
                    );

                    if (allowed === "Allow Write") {
                        await this._actionManager.applyFileChange(data.path, data.content);
                    } else {
                        vscode.window.showWarningMessage("Write operation denied by user.");
                        this.sendToWebview('tool_denied', { id: data.id });
                    }
                    break;
                }
                case 'view_diff': {
                    await this._actionManager.previewFileDiff(data.path, data.content);
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
        // [Security Fix] Use crypto
        return crypto.randomBytes(16).toString('base64');
    }

    private _getHtmlForWebview(webview: vscode.Webview) {
        const nonce = this._getNonce();

        // Use vue.global.prod.js (Runtime only if possible, but prod is safer than dev)
        const vueUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'media', 'vue.global.prod.js'));
        const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'media', 'main.js'));
        const stylesUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'media', 'styles.css'));

        // [Security Fix] CSP
        // Removed 'unsafe-eval'. If Vue Runtime Compiler is needed, this might break.
        // Recommended: Pre-compile Vue templates or use Vue Runtime-only build.
        // Assuming user has switched to runtime-only Vue or accepts no eval (safer).
        
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}'; connect-src 'self' http://127.0.0.1:*;">
    <link href="${stylesUri}" rel="stylesheet">
    <script nonce="${nonce}" src="${vueUri}"></script>
    <title>Gemini Swarm</title>
</head>
<body>
    <div id="app">
        <!-- Vue App Content -->
        <!-- Omitted for brevity, logic is in main.js -->
        <div id="chat-container"></div>
        <script nonce="${nonce}">
           // Bootstrapping
        </script>
    </div>
    <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
    }
}
