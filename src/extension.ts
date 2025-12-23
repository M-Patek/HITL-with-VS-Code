import * as vscode from 'vscode';
import { ProcessManager } from './managers/processManager';
import { ChatViewProvider } from './views/chatProvider';
import { GeminiQuickFixProvider } from './providers/quickFixProvider';
import { SecurityManager } from './managers/securityManager';
import { DependencyManager } from './managers/dependencyManager';
import { ActionManager } from './managers/actionManager';
import { GitManager } from './managers/gitManager';
import { GeminiInlineCompletionProvider } from './providers/completionProvider'; // [Phase 3]

let processManager: ProcessManager;

export async function activate(context: vscode.ExtensionContext) {
    processManager = new ProcessManager();
    const securityManager = new SecurityManager();
    const dependencyManager = new DependencyManager();
    const chatProvider = new ChatViewProvider(context.extensionUri);
    const actionManager = ActionManager.getInstance();
    const gitManager = new GitManager(); // [Phase 3] Need instance for commands

    securityManager.checkDockerAvailability();

    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(ChatViewProvider.viewType, chatProvider)
    );

    // [Phase 3 Upgrade] Register Inline Completion Provider
    const completionProvider = new GeminiInlineCompletionProvider();
    context.subscriptions.push(
        vscode.languages.registerInlineCompletionItemProvider(
            { pattern: '**' }, // Apply to all files
            completionProvider
        )
    );

    context.subscriptions.push(
        vscode.languages.registerCodeActionsProvider(
            GeminiQuickFixProvider.selector,
            new GeminiQuickFixProvider(),
            { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }
        )
    );

    // Commands...
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

    // [Phase 3 Upgrade] Semantic Commit Command
    context.subscriptions.push(
        vscode.commands.registerCommand('gemini-swarm.semanticCommit', async (msg: string) => {
            // Confirm with user
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
