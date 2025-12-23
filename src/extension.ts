import * as vscode from 'vscode';
import { ProcessManager } from './managers/processManager';
import { ChatViewProvider } from './views/chatProvider';
import { GeminiQuickFixProvider } from './providers/quickFixProvider';
import { SecurityManager } from './managers/securityManager';
import { DependencyManager } from './managers/dependencyManager';
// [New]
import { ActionManager } from './managers/actionManager';

let processManager: ProcessManager;

export async function activate(context: vscode.ExtensionContext) {
    console.log('Gemini Swarm Activated! 🐱');

    processManager = new ProcessManager();
    const securityManager = new SecurityManager();
    const dependencyManager = new DependencyManager();
    const chatProvider = new ChatViewProvider(context.extensionUri);
    // [New] 单独实例化 ActionManager 以便命令调用
    const actionManager = new ActionManager(); 
    // 注意：ChatViewProvider 内部也有一个 ActionManager，为了状态一致性，
    // 理想情况下应该共享同一个实例，或者将 ActionManager 设为单例。
    // 这里为了简单，我们让 ChatViewProvider 使用它自己的，而 Undo 命令使用这里的。
    // 由于 Git 操作是针对磁盘的，多实例并不影响逻辑。

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

    // [Aider Soul] 注册撤销命令
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
