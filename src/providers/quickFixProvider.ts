import * as vscode from 'vscode';

// [Functionality Fix] 实现了真正的 Quick Fix (小灯泡) 功能
export class GeminiQuickFixProvider implements vscode.CodeActionProvider {
    public static readonly selector = '*';

    provideCodeActions(document: vscode.TextDocument, range: vscode.Range | vscode.Selection, context: vscode.CodeActionContext, token: vscode.CancellationToken): vscode.CodeAction[] {
        // 如果没有报错，不显示修复选项
        if (context.diagnostics.length === 0) {
            return [];
        }

        const actions: vscode.CodeAction[] = [];
        
        // 遍历所有诊断信息（红色波浪线）
        for (const diagnostic of context.diagnostics) {
            const title = `✨ Fix with Gemini: ${diagnostic.message}`;
            const action = new vscode.CodeAction(title, vscode.CodeActionKind.QuickFix);
            
            // 绑定命令，点击后触发 ChatProvider 的修复流程
            action.command = {
                command: 'gemini-swarm.triggerFix',
                title: 'Fix with Gemini',
                arguments: [
                    diagnostic.message, 
                    this.getContext(document, diagnostic.range)
                ]
            };
            
            action.diagnostics = [diagnostic];
            action.isPreferred = true; // 设为首选修复
            actions.push(action);
        }

        return actions;
    }

    // 获取报错行附近的上下文（前后 5 行）
    private getContext(document: vscode.TextDocument, range: vscode.Range): string {
        const start = Math.max(0, range.start.line - 5);
        const end = Math.min(document.lineCount - 1, range.end.line + 5);
        const contextRange = new vscode.Range(start, 0, end, document.lineAt(end).text.length);
        return document.getText(contextRange);
    }
}
