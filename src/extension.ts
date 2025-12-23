import * as vscode from 'vscode';
import { ProcessManager } from './managers/processManager';
import { ChatViewProvider } from './views/chatProvider';
import { GeminiQuickFixProvider } from './providers/quickFixProvider';
import { GeminiInlineCompletionProvider } from './providers/completionProvider';
import { DockerHealthCheck } from './managers/dockerHealthCheck'; // New name
import { DependencyManager } from './managers/dependencyManager';
import { ActionManager } from './managers/actionManager';
import { GitManager } from './managers/gitManager';

let processManager: ProcessManager;

export async function activate(context: vscode.ExtensionContext) {
    // 1. 初始化所有管理器
    processManager = new ProcessManager();
    const dockerCheck = new DockerHealthCheck();
    const dependencyManager = new DependencyManager();
    const actionManager = ActionManager.getInstance();
    const gitManager = new GitManager(); 

    // 2. 注册资源释放 (Disposables)
    // 确保插件禁用时能清理 OutputChannel
    context.subscriptions.push(processManager);
    context.subscriptions.push(dependencyManager);
    context.subscriptions.push(actionManager);
    context.subscriptions.push(gitManager);

    // 3. 注册 UI 与 Providers
    const chatProvider = new ChatViewProvider(context.extensionUri);
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(ChatViewProvider.viewType, chatProvider)
    );

    // [Fix] 注册分离后的 Completion Provider
    const completionProvider = new GeminiInlineCompletionProvider();
    context.subscriptions.push(
        vscode.languages.registerInlineCompletionItemProvider(
            { pattern: '**' }, 
            completionProvider
        )
    );

    // [Fix] 注册分离后的 Quick Fix Provider
    context.subscriptions.push(
        vscode.languages.registerCodeActionsProvider(
            GeminiQuickFixProvider.selector,
            new GeminiQuickFixProvider(),
            { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }
        )
    );

    // 4. 后台检查
    dockerCheck.checkDockerAvailability();

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

    context.subscriptions.push(
        vscode.commands.registerCommand('gemini-swarm.installDependencies', () => {
            dependencyManager.installDependencies(context);
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('gemini-swarm.undoLastChange', () => {
            actionManager.undoLastChange();
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('gemini-swarm.semanticCommit', async (msg: string) => {
            const choice = await vscode.window.showInformationMessage(
                `Gemini wants to commit: "${msg}"`,
                "Commit", "Edit"
            );
            
            if (choice === "Commit") {
                await gitManager.doSemanticCommit(msg);
            } else if (choice === "Edit") {
                const newMsg = await vscode.window.showInputBox({ value: msg, prompt: "Edit commit message" });
                if (newMsg) await gitManager.doSemanticCommit(newMsg);
            }
        })
    );
}

export function deactivate() {
    if (processManager) {
        processManager.dispose();
    }
}
