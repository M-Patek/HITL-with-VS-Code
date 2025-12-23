import * as vscode from 'vscode';
import * as path from 'path';

export interface FileContext {
    filename: string;
    content: string;
    selection: string;
    cursor_line: number;
    language_id: string;
}

export class ContextManager {
    
    /**
     * 获取当前激活编辑器的详细上下文
     */
    public getActiveFileContext(): FileContext | null {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            return null;
        }

        const document = editor.document;
        const selection = editor.selection;
        const cursorPosition = selection.active;

        return {
            filename: path.basename(document.fileName),
            content: document.getText(),
            selection: document.getText(selection), // 如果没选中，这里是空字符串
            cursor_line: cursorPosition.line + 1, // 转为人类可读的 1-based 行号
            language_id: document.languageId
        };
    }

    /**
     * 获取当前文件的诊断信息（报错/警告）
     * 这让 AI 能自动修复红波浪线
     */
    public getDiagnostics(): string {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            return "";
        }

        const diagnostics = vscode.languages.getDiagnostics(editor.document.uri);
        if (diagnostics.length === 0) {
            return "";
        }

        return diagnostics.map(d => {
            const range = `L${d.range.start.line + 1}:C${d.range.start.character}`;
            return `[${vscode.DiagnosticSeverity[d.severity]}] ${range} - ${d.message}`;
        }).join('\n');
    }

    /**
     * 扫描项目结构（轻量级）
     * 排除 node_modules, .git 等干扰项，生成类似 tree 命令的结构
     */
    public async getProjectStructure(): Promise<string> {
        if (!vscode.workspace.workspaceFolders) {
            return "No workspace folder open.";
        }

        // 使用 VS Code 内置的 findFiles，它会自动遵循 .gitignore
        // 限制最多 50 个文件，防止 Token 爆炸
        const excludePattern = '**/{node_modules,.git,dist,out,build,.vscode,__pycache__}/**';
        const uris = await vscode.workspace.findFiles('**/*', excludePattern, 50);

        const filePaths = uris.map(uri => vscode.workspace.asRelativePath(uri));
        
        // 简单格式化为列表，如果需要树状图可以用更复杂的逻辑，但列表对 LLM 也很友好
        return filePaths.join('\n');
    }

    /**
     * 打包所有上下文
     */
    public async collectFullContext(): Promise<any> {
        const fileCtx = this.getActiveFileContext();
        const structure = await this.getProjectStructure();
        
        // 如果有报错，把它追加到用户的 input 或者作为单独字段传给后端
        // 这里我们选择不改变 API 结构，而是让前端处理如何拼接
        const diagnostics = this.getDiagnostics();

        return {
            file_context: fileCtx,
            project_structure: structure,
            diagnostics: diagnostics
        };
    }
}
