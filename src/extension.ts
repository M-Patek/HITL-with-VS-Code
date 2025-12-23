import * as vscode from 'vscode';
import { ProcessManager } from './managers/processManager';
import { ChatViewProvider } from './views/chatProvider';
import { GeminiQuickFixProvider } from './providers/quickFixProvider';
import { SecurityManager } from './managers/securityManager';
import { DependencyManager } from './managers/dependencyManager';
import { ActionManager } from './managers/actionManager';

let processManager: ProcessManager;

export async function activate(context: vscode.ExtensionContext) {
    // [Cleanup] Remove console.log in production
    // console.log('Gemini Swarm Activated! 🐱'); 

    processManager = new ProcessManager();
    const securityManager = new SecurityManager();
    const dependencyManager = new DependencyManager();
    const chatProvider = new ChatViewProvider(context.extensionUri);
    const actionManager = ActionManager.getInstance();

    // 非阻塞检查 Docker
    securityManager.checkDockerAvailability();

    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(ChatViewProvider.viewType, chatProvider)
    );

    context.subscriptions.push(
        vscode.languages.registerCodeActionsProvider(
            GeminiQuickFixProvider.selector,
            new GeminiQuickFixProvider(),
            { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }
        )
    );

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
}

export function deactivate() {
    if (processManager) {
        processManager.dispose();
    }
}
