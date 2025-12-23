import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { GitManager } from './gitManager';

export class ActionManager implements vscode.Disposable {
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

    public dispose() {
        if (ActionManager._terminal) {
            ActionManager._terminal.dispose();
            ActionManager._terminal = undefined;
        }
        this._gitManager.dispose();
    }

    private async ensureCheckpoint(context: string) {
        if (await this._gitManager.isGitRepo()) {
            await this._gitManager.createCheckpoint(`Gemini Swarm: Pre-change checkpoint (${context})`);
        }
    }

    private validatePath(relativePath: string): string | null {
        if (!vscode.workspace.workspaceFolders) return null;

        const rootPath = vscode.workspace.workspaceFolders[0].uri.fsPath;
        // [Security Fix] Resolve and Normalize to prevent traversal
        const fullPath = path.normalize(path.resolve(rootPath, relativePath));
        
        // Ensure it is still within root
        if (!fullPath.startsWith(rootPath)) {
            vscode.window.showErrorMessage(`❌ Security Alert: Path traversal attempt blocked! (${relativePath})`);
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
        const header = "⚠️ GEMINI SWARM SECURITY CHECK ⚠️\n\nThe AI wants to execute the following command in your terminal.\nPlease review it CAREFULLY before approving.\n\nCOMMAND:\n";
        const docContent = header + "-".repeat(50) + "\n" + command + "\n" + "-".repeat(50);
        
        const doc = await vscode.workspace.openTextDocument({ content: docContent, language: 'shellscript' });
        await vscode.window.showTextDocument(doc, { preview: true, viewColumn: vscode.ViewColumn.Beside });

        const selection = await vscode.window.showWarningMessage(
            `Review the command in the editor. Allow execution?`,
            { modal: true },
            "✅ Execute", "🚫 Cancel"
        );
        
        vscode.commands.executeCommand('workbench.action.closeActiveEditor');

        if (selection !== "✅ Execute") return;

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

        const isGit = await this._gitManager.isGitRepo();
        if (isGit) {
            await this.ensureCheckpoint(`Update ${relativePath}`);
        } else {
            try {
                if (fs.existsSync(fullPath)) {
                    const backupPath = `${fullPath}.bak`;
                    await fs.promises.copyFile(fullPath, backupPath);
                }
            } catch (e: any) {
                const msg = `❌ Backup failed for ${relativePath}: ${e.message}. Operation aborted for safety.`;
                vscode.window.showErrorMessage(msg);
                throw new Error(msg);
            }
        }

        try {
            const dir = path.dirname(fullPath);
            await fs.promises.mkdir(dir, { recursive: true });
            await fs.promises.writeFile(fullPath, content, 'utf8');
            vscode.window.showInformationMessage(`✅ File updated: ${relativePath}`);
        } catch (e: any) {
            vscode.window.showErrorMessage(`❌ Failed to write file: ${e.message}`);
        }
    }

    public async applySmartDiff(relativePath: string, searchBlock: string, replaceBlock: string) {
        const fullPath = this.validatePath(relativePath);
        if (!fullPath) return;

        try {
            if (!fs.existsSync(fullPath)) {
                vscode.window.showErrorMessage(`❌ Diff failed: File not found ${relativePath}`);
                return;
            }

            const fileContent = await fs.promises.readFile(fullPath, 'utf8');
            const fileLines = fileContent.split(/\r?\n/);
            const searchLines = searchBlock.split(/\r?\n/).map(l => l.trim()).filter(l => l !== "");
            
            if (searchLines.length === 0) {
                 vscode.window.showErrorMessage("❌ Diff failed: Empty search block.");
                 return;
            }

            // [Robustness Fix] Strict Multi-Match Detection
            const matchedIndices: number[] = [];

            for (let i = 0; i <= fileLines.length - searchLines.length; i++) {
                let match = true;
                let fileCursor = i;
                
                for (let j = 0; j < searchLines.length; j++) {
                    // Skip empty lines in source
                    while (fileCursor < fileLines.length && fileLines[fileCursor].trim() === "") {
                        fileCursor++;
                    }
                    
                    if (fileCursor >= fileLines.length || fileLines[fileCursor].trim() !== searchLines[j]) {
                        match = false;
                        break;
                    }
                    fileCursor++;
                }

                if (match) {
                    matchedIndices.push(i);
                }
            }

            if (matchedIndices.length === 0) {
                vscode.window.showErrorMessage(`❌ Diff failed: Could not locate code block in ${relativePath}`);
                return;
            }

            if (matchedIndices.length > 1) {
                vscode.window.showErrorMessage(`❌ Diff failed: Ambiguous match. Found ${matchedIndices.length} occurrences of the code block. Please provide more context.`);
                return;
            }

            const matchIndex = matchedIndices[0];

            // Reconstruct file content
            let fileCursor = matchIndex;
            for (let j = 0; j < searchLines.length; j++) {
                 while (fileCursor < fileLines.length && fileLines[fileCursor].trim() === "") {
                    fileCursor++;
                }
                fileCursor++; 
            }

            const before = fileLines.slice(0, matchIndex).join('\n');
            const after = fileLines.slice(fileCursor).join('\n');
            
            const newContent = (before ? before + '\n' : '') + replaceBlock + (after ? '\n' + after : '');

            await this.applyFileChange(relativePath, newContent);
            
        } catch (e: any) {
            vscode.window.showErrorMessage(`❌ Diff Error: ${e.message}`);
        }
    }
    
    public async undoLastChange() {
        await this._gitManager.undoLastCommit();
    }
}
