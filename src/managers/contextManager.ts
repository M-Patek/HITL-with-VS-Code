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
    
    public getActiveFileContext(): FileContext | null {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            return null;
        }

        const document = editor.document;
        const selection = editor.selection;
        const cursorPosition = selection.active;

        // [Optimization] 使用相对路径解决文件名歧义
        const filename = vscode.workspace.asRelativePath(document.fileName);

        return {
            filename: filename,
            content: document.getText(),
            selection: document.getText(selection), 
            cursor_line: cursorPosition.line + 1,
            language_id: document.languageId
        };
    }

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

    public async getProjectStructure(): Promise<string> {
        if (!vscode.workspace.workspaceFolders) {
            return "No workspace folder open.";
        }

        const excludePattern = '**/{node_modules,.git,dist,out,build,.vscode,__pycache__}/**';
        const uris = await vscode.workspace.findFiles('**/*', excludePattern, 50);

        const filePaths = uris.map(uri => vscode.workspace.asRelativePath(uri));
        return filePaths.join('\n');
    }

    public async collectFullContext(): Promise<any> {
        const fileCtx = this.getActiveFileContext();
        const structure = await this.getProjectStructure();
        const diagnostics = this.getDiagnostics();

        return {
            file_context: fileCtx,
            project_structure: structure,
            diagnostics: diagnostics
        };
    }
}
