import * as vscode from 'vscode';

export class GeminiQuickFixProvider implements vscode.CodeActionProvider {
    
    // 注册为通用文件处理器
    public static readonly selector = { scheme: 'file' };

    provideCodeActions(
        document: vscode.TextDocument, 
        range: vscode.Range | vscode.Selection, 
        context: vscode.CodeActionContext, 
        token: vscode.CancellationToken
    ): vscode.ProviderResult<(vscode.Command | vscode.CodeAction)[]> {
        
        // 只处理报错信息
        const diagnostics = context.diagnostics;
        if (diagnostics.length === 0) {
            return [];
        }

        const actions: vscode.CodeAction[] = [];

        // 为每个报错生成一个修复选项
        for (const diagnostic of diagnostics) {
            const action = new vscode.CodeAction(
                `✨ Fix with Gemini Swarm: ${diagnostic.message}`, 
                vscode.CodeActionKind.QuickFix
            );
            
            // 关联一个命令，该命令会通知 ChatView
            action.command = {
                command: 'gemini-swarm.triggerFix',
                title: 'Fix with Gemini',
                arguments: [diagnostic.message, document.getText(diagnostic.range)]
            };
            
            // 标记该 Action 解决了哪个 Diagnostic
            action.diagnostics = [diagnostic];
            action.isPreferred = true; // 设为首选修复
            
            actions.push(action);
        }

        return actions;
    }
}
