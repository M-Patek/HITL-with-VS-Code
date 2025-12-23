import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { GitManager } from './gitManager';

export class ActionManager {
    private static _instance: ActionManager;
    private static _terminal: vscode.Terminal | undefined;
    private _gitManager: GitManager;

    private constructor() {
        this._gitManager = new GitManager();
    }

    public static getInstance(): ActionManager {
        if (!ActionManager._instance) {
            ActionManager._instance = new ActionManager();
        }
        return ActionManager._instance;
    }

    private async ensureCheckpoint(context: string) {
        if (await this._gitManager.isGitRepo()) {
            await this._gitManager.createCheckpoint(`Gemini Swarm: Pre-change checkpoint (${context})`);
        }
    }

    /**
     * [Security Fix] 验证路径是否在工作区内，防止路径遍历攻击
     */
    private validatePath(relativePath: string): string | null {
        if (!vscode.workspace.workspaceFolders) return null;

        const rootPath = vscode.workspace.workspaceFolders[0].uri.fsPath;
        // 使用 path.resolve 处理 '..'
        const fullPath = path.resolve(rootPath, relativePath);
        
        // 确保解析后的绝对路径以 rootPath 开头
        // 注意：Windows 上路径不区分大小写，这里进行简单的大小写不敏感检查更安全，
        // 或者直接依赖 path.relative 检查是否以 '..' 开头
        const relative = path.relative(rootPath, fullPath);
        if (relative.startsWith('..') || path.isAbsolute(relative)) {
            vscode.window.showErrorMessage(`❌ Security Alert: Illegal path access detected! (${relativePath})`);
            return null;
        }

        return fullPath;
    }

    public async insertCode(editor: vscode.TextEditor, code: string) {
        await this.ensureCheckpoint('Insert Code');
        await editor.edit(editBuilder => {
            if (!editor.selection.isEmpty) {
                editBuilder.replace(editor.selection, code);
            } else {
                editBuilder.insert(editor.selection.active, code);
            }
        });
    }

    public async previewFileDiff(relativePath: string, newContent: string) {
        const fullPath = this.validatePath(relativePath);
        if (!fullPath) return;

        const fileName = path.basename(relativePath);
        const tempNewUri = vscode.Uri.file(path.join(os.tmpdir(), `gemini_new_${Date.now()}_${fileName}`));
        await fs.promises.writeFile(tempNewUri.fsPath, newContent);

        let leftUri = vscode.Uri.file(fullPath);
        let title = `${fileName} (Current) ↔ (Gemini Proposal)`;

        try {
            await fs.promises.access(fullPath);
        } catch {
            const tempEmptyUri = vscode.Uri.file(path.join(os.tmpdir(), `gemini_empty_${Date.now()}_${fileName}`));
            await fs.promises.writeFile(tempEmptyUri.fsPath, "");
            leftUri = tempEmptyUri;
            title = `(New File) ${fileName} ↔ (Gemini Proposal)`;
        }

        await vscode.commands.executeCommand(
            'vscode.diff',
            leftUri,
            tempNewUri,
            title,
            { preview: true }
        );
    }

    public async runInTerminal(command: string) {
        const selection = await vscode.window.showWarningMessage(
            `Gemini Swarm wants to run: "${command}". Allow?`,
            { modal: true },
            "Run", "Cancel"
        );

        if (selection !== "Run") return;

        if (!ActionManager._terminal || ActionManager._terminal.exitStatus !== undefined) {
            ActionManager._terminal = vscode.window.createTerminal({
                name: "Gemini Swarm Terminal",
                iconPath: new vscode.ThemeIcon("robot")
            });
        }
        
        ActionManager._terminal.show();
        ActionManager._terminal.sendText(command);
    }

    public async applyFileChange(relativePath: string, content: string) {
        const fullPath = this.validatePath(relativePath);
        if (!fullPath) return;

        await this.ensureCheckpoint(`Update ${relativePath}`);

        try {
            const dir = path.dirname(fullPath);
            await fs.promises.mkdir(dir, { recursive: true });
            
            await fs.promises.writeFile(fullPath, content, 'utf8');
            
            vscode.window.showInformationMessage(`✅ File updated: ${relativePath}`);
            
            try {
                const doc = await vscode.workspace.openTextDocument(fullPath);
                await vscode.window.showTextDocument(doc);
            } catch {}
            
        } catch (e: any) {
            vscode.window.showErrorMessage(`❌ Failed to write file: ${e.message}`);
        }
    }
    
    public async undoLastChange() {
        await this._gitManager.undoLastCommit();
    }
}
