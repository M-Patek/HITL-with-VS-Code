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
        if (!vscode.workspace.workspaceFolders) {
            vscode.window.showErrorMessage('No workspace open for diff!');
            return;
        }

        const rootPath = vscode.workspace.workspaceFolders[0].uri.fsPath;
        const targetPath = path.join(rootPath, relativePath);
        
        // [Security] Path Traversal Check
        if (!targetPath.startsWith(rootPath)) {
            vscode.window.showErrorMessage('❌ Security Alert: Illegal path access detected!');
            return;
        }

        const fileName = path.basename(relativePath);
        const tempNewUri = vscode.Uri.file(path.join(os.tmpdir(), `gemini_new_${Date.now()}_${fileName}`));
        await fs.promises.writeFile(tempNewUri.fsPath, newContent);

        let leftUri = vscode.Uri.file(targetPath);
        let title = `${fileName} (Current) ↔ (Gemini Proposal)`;

        try {
            await fs.promises.access(targetPath);
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
        if (!vscode.workspace.workspaceFolders) {
            vscode.window.showErrorMessage('No workspace open!');
            return;
        }

        const rootPath = vscode.workspace.workspaceFolders[0].uri.fsPath;
        const fullPath = path.join(rootPath, relativePath);

        // [Security] Path Traversal Check
        if (!fullPath.startsWith(rootPath)) {
            vscode.window.showErrorMessage('❌ Security Alert: Illegal path access detected!');
            return;
        }

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
