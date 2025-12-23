import * as vscode from 'vscode';
import { ProcessManager } from './managers/processManager';
import { ChatViewProvider } from './views/chatProvider';
import { GeminiQuickFixProvider } from './providers/quickFixProvider';
import { SecurityManager } from './managers/securityManager'; // [New]
import { DependencyManager } from './managers/dependencyManager'; // [New]

let processManager: ProcessManager;

export async function activate(context: vscode.ExtensionContext) {
    console.log('Gemini Swarm Activated! 🐱');

    // 1. 初始化各路管理器
    processManager = new ProcessManager();
    const securityManager = new SecurityManager(); // [New]
    const dependencyManager = new DependencyManager(); // [New]
    const chatProvider = new ChatViewProvider(context.extensionUri);

    // 2. 执行启动前检查 (不阻塞 UI)
    securityManager.checkDockerAvailability();

    // 3. 注册 Webview
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(ChatViewProvider.viewType, chatProvider)
    );

    // 4. 注册 Quick Fix
    context.subscriptions.push(
        vscode.languages.registerCodeActionsProvider(
            GeminiQuickFixProvider.selector,
            new GeminiQuickFixProvider(),
            { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }
        )
    );

    // 5. 注册命令
    context.subscriptions.push(
        vscode.commands.registerCommand('gemini-swarm.startEngine', async () => {
            const success = await processManager.start(context);
            if (success) vscode.commands.executeCommand('gemini-swarm.chatView.focus');
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('gemini-swarm.stopEngine', () => processManager.stop())
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('gemini-swarm.showPanel', () => {
            vscode.commands.executeCommand('gemini-swarm.chatView.focus');
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('gemini-swarm.triggerFix', (errorMsg: string, errorContext: string) => {
            chatProvider.triggerFixFlow(errorMsg, errorContext);
        })
    );

    // [New] 注册依赖安装命令
    context.subscriptions.push(
        vscode.commands.registerCommand('gemini-swarm.installDependencies', () => {
            dependencyManager.installDependencies(context);
        })
    );
}

export function deactivate() {
    if (processManager) {
        processManager.dispose();
    }
}
