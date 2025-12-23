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
    
    // [Privacy Fix] Filter sensitive files
    private isSensitiveFile(filename: string): boolean {
        const lower = filename.toLowerCase();
        if (lower.endsWith('.env') || lower.includes('credentials') || lower.includes('secret') || lower.includes('id_rsa')) {
            return true;
        }
        return false;
    }

    public getActiveFileContext(): FileContext | null {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            return null;
        }

        const document = editor.document;
        const filename = vscode.workspace.asRelativePath(document.fileName);

        // [Privacy Fix] Redact sensitive files
        if (this.isSensitiveFile(filename)) {
            return {
                filename: filename,
                content: "[REDACTED - SENSITIVE FILE]",
                selection: "",
                cursor_line: 0,
                language_id: document.languageId
            };
        }

        // [Performance Fix] Hard limit on size (e.g., 100KB)
        const rawText = document.getText();
        let content = rawText;
        if (rawText.length > 100 * 1024) {
            content = rawText.substring(0, 100 * 1024) + "\n\n[...TRUNCATED BY SYSTEM DUE TO SIZE...]";
        }

        const selection = editor.selection;
        const cursorPosition = selection.active;

        return {
            filename: filename,
            content: content,
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

        const excludePattern = '**/{node_modules,.git,dist,out,build,.vscode,__pycache__,venv,env,.env}/**';
        const uris = await vscode.workspace.findFiles('**/*', excludePattern, 200); // Increased limit slightly

        const filePaths = uris.map(uri => vscode.workspace.asRelativePath(uri));
        // [Privacy Fix] Double check list for sensitive files
        const cleanPaths = filePaths.filter(p => !this.isSensitiveFile(p));
        
        return cleanPaths.join('\n');
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
