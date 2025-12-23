import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { GitManager } from './gitManager';

export class ActionManager {
    private static _terminal: vscode.Terminal | undefined;
    private _gitManager: GitManager;

    constructor() {
        this._gitManager = new GitManager();
    }

    private async ensureCheckpoint(context: string) {
        if (await this._gitManager.isGitRepo()) {
            await this._gitManager.createCheckpoint(`Gemini Swarm: Pre-change checkpoint (${context})`);
        }
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

    /**
     * [Roo Code Soul] 交互式 Diff 预览
     * 对比 "当前文件" (Left) 与 "AI 建议" (Right)
     */
    public async previewFileDiff(relativePath: string, newContent: string) {
        if (!vscode.workspace.workspaceFolders) {
            vscode.window.showErrorMessage('No workspace open for diff!');
            return;
        }

        const rootPath = vscode.workspace.workspaceFolders[0].uri.fsPath;
        const targetPath = path.join(rootPath, relativePath);
        const fileName = path.basename(relativePath);

        // 1. 创建右侧（新内容）的临时文件
        // 使用随机后缀避免冲突
        const tempNewUri = vscode.Uri.file(path.join(os.tmpdir(), `gemini_new_${Date.now()}_${fileName}`));
        await fs.promises.writeFile(tempNewUri.fsPath, newContent);

        // 2. 确定左侧（旧内容）
        let leftUri = vscode.Uri.file(targetPath);
        let title = `${fileName} (Current) ↔ (Gemini Proposal)`;

        try {
            // 检查文件是否存在
            await fs.promises.access(targetPath);
        } catch {
            // 文件不存在（是新建文件），左侧展示一个空的临时文件
            const tempEmptyUri = vscode.Uri.file(path.join(os.tmpdir(), `gemini_empty_${Date.now()}_${fileName}`));
            await fs.promises.writeFile(tempEmptyUri.fsPath, "");
            leftUri = tempEmptyUri;
            title = `(New File) ${fileName} ↔ (Gemini Proposal)`;
        }

        // 3. 打开 Diff 视图
        await vscode.commands.executeCommand(
            'vscode.diff',
            leftUri,
            tempNewUri,
            title,
            { preview: true } // 在预览标签页打开
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
        if (!vscode.workspace.workspaceFolders) {
            vscode.window.showErrorMessage('No workspace open!');
            return;
        }

        await this.ensureCheckpoint(`Update ${relativePath}`);

        const rootPath = vscode.workspace.workspaceFolders[0].uri.fsPath;
        const fullPath = path.join(rootPath, relativePath);

        try {
            const dir = path.dirname(fullPath);
            await fs.promises.mkdir(dir, { recursive: true });
            
            await fs.promises.writeFile(fullPath, content, 'utf8');
            
            vscode.window.showInformationMessage(`✅ File updated: ${relativePath}`);
            
            // 写入后尝试打开文件
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
