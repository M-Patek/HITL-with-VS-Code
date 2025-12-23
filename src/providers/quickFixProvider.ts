import * as vscode from 'vscode';
import axios from 'axios';
import { ProcessManager } from '../managers/processManager';

export class GeminiInlineCompletionProvider implements vscode.InlineCompletionItemProvider {
    private debounceTimer: NodeJS.Timeout | undefined;
    private requestController: AbortController | undefined;

    public async provideInlineCompletionItems(
        document: vscode.TextDocument,
        position: vscode.Position,
        context: vscode.InlineCompletionContext,
        token: vscode.CancellationToken
    ): Promise<vscode.InlineCompletionItem[] | undefined> {
        
        // 1. Basic Checks
        const port = ProcessManager.getActivePort();
        if (!port) return undefined;

        // Skip if triggered explicitly by typing a character that shouldn't trigger (optional optimization)
        
        // 2. Debounce & Cancellation
        if (this.debounceTimer) clearTimeout(this.debounceTimer);
        if (this.requestController) this.requestController.abort();

        return new Promise((resolve) => {
            this.debounceTimer = setTimeout(async () => {
                if (token.isCancellationRequested) {
                    resolve(undefined);
                    return;
                }

                try {
                    // 3. Prepare Context
                    // Get ~20 lines before and after for context window
                    const startLine = Math.max(0, position.line - 20);
                    const endLine = Math.min(document.lineCount - 1, position.line + 20);
                    
                    const prefixRange = new vscode.Range(new vscode.Position(startLine, 0), position);
                    const suffixRange = new vscode.Range(position, new vscode.Position(endLine, document.lineAt(endLine).text.length));
                    
                    const prefix = document.getText(prefixRange);
                    const suffix = document.getText(suffixRange);
                    
                    this.requestController = new AbortController();

                    // 4. Call Python Backend (Fast FIM)
                    const response = await axios.post(`http://127.0.0.1:${port}/api/completion`, {
                        prefix: prefix,
                        suffix: suffix,
                        file_path: document.fileName,
                        language: document.languageId
                    }, {
                        signal: this.requestController.signal,
                        timeout: 3000 // 3s Max timeout for completion
                    });

                    const completionText = response.data.completion;
                    
                    if (!completionText || completionText.trim().length === 0) {
                        resolve(undefined);
                        return;
                    }

                    // 5. Return Item
                    const item = new vscode.InlineCompletionItem(
                        completionText,
                        new vscode.Range(position, position)
                    );
                    item.command = { command: 'gemini-swarm.acceptCompletion', title: 'Accept' };
                    
                    resolve([item]);

                } catch (e) {
                    // console.error(e);
                    resolve(undefined);
                }
            }, 300); // 300ms Debounce
        });
    }
}
