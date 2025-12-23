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

    private validatePath(relativePath: string): string | null {
        if (!vscode.workspace.workspaceFolders) return null;

        const rootPath = vscode.workspace.workspaceFolders[0].uri.fsPath;
        const fullPath = path.resolve(rootPath, relativePath);
        
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

        const isGit = await this._gitManager.isGitRepo();
        if (isGit) {
            await this.ensureCheckpoint(`Update ${relativePath}`);
        } else {
            try {
                if (fs.existsSync(fullPath)) {
                    const backupPath = `${fullPath}.bak`;
                    await fs.promises.copyFile(fullPath, backupPath);
                }
            } catch (e) {
                console.warn("Failed to create backup", e);
            }
        }

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

    /**
     * [Phase 2 Upgrade] Smart Diff Application
     * Applies search_block / replace_block with fuzzy matching (ignoring whitespace).
     */
    public async applySmartDiff(relativePath: string, searchBlock: string, replaceBlock: string) {
        const fullPath = this.validatePath(relativePath);
        if (!fullPath) return;

        try {
            if (!fs.existsSync(fullPath)) {
                vscode.window.showErrorMessage(`❌ Apply Diff Failed: File not found ${relativePath}`);
                return;
            }

            const originalContent = await fs.promises.readFile(fullPath, 'utf8');
            
            // 1. Try Exact Match First
            if (originalContent.includes(searchBlock)) {
                const newContent = originalContent.replace(searchBlock, replaceBlock);
                await this.applyFileChange(relativePath, newContent);
                return;
            }

            // 2. Fuzzy Match (Line by Line, ignore whitespace)
            // This is a simplified implementation of Aider's diff logic
            const lines = originalContent.split(/\r?\n/);
            const searchLines = searchBlock.split(/\r?\n/).map(l => l.trim()).filter(l => l.length > 0);
            
            if (searchLines.length === 0) {
                 vscode.window.showErrorMessage(`❌ Apply Diff Failed: Empty search block.`);
                 return;
            }

            let matchIndex = -1;
            
            // Sliding window search
            for (let i = 0; i < lines.length; i++) {
                let match = true;
                for (let j = 0; j < searchLines.length; j++) {
                    if (i + j >= lines.length) {
                        match = false;
                        break;
                    }
                    if (lines[i + j].trim() !== searchLines[j]) {
                        match = false;
                        break;
                    }
                }
                if (match) {
                    matchIndex = i;
                    break;
                }
            }

            if (matchIndex !== -1) {
                // Determine the range to replace in original lines
                // We need to be careful about how many lines we are actually replacing
                // because we filtered searchLines.
                
                // Heuristic: Find the start line in original text that matched searchLines[0]
                // and end line that matched searchLines[last]
                
                // A safer approach for this simple version:
                // Re-construct the new content by slicing arrays
                // Note: This replaces the matched lines with replaceBlock directly.
                // It might lose some indentation of the original block if replaceBlock doesn't have it.
                // But usually LLM provides indentation in replaceBlock.

                // Calculate the actual number of lines in original file that were covered by the fuzzy match
                // We need to walk forward from matchIndex until we satisfy all searchLines
                let originalCoveredCount = 0;
                let searchPtr = 0;
                let currentIdx = matchIndex;
                
                while (searchPtr < searchLines.length && currentIdx < lines.length) {
                    if (lines[currentIdx].trim() === searchLines[searchPtr]) {
                        searchPtr++;
                    }
                    originalCoveredCount++;
                    currentIdx++;
                }

                const before = lines.slice(0, matchIndex).join('\n');
                const after = lines.slice(matchIndex + originalCoveredCount).join('\n');
                const newContent = (before ? before + '\n' : '') + replaceBlock + (after ? '\n' + after : '');
                
                await this.applyFileChange(relativePath, newContent);
                vscode.window.showInformationMessage(`✅ Smart Diff Applied to ${relativePath}`);
            } else {
                vscode.window.showErrorMessage(`❌ Apply Diff Failed: Could not locate search block in ${relativePath}`);
                // Optional: Show diff view of what was expected vs what is there?
            }

        } catch (e: any) {
            vscode.window.showErrorMessage(`❌ Diff Error: ${e.message}`);
        }
    }
    
    public async undoLastChange() {
        if (await this._gitManager.isGitRepo()) {
            const lastMessage = await this._gitManager.getLastCommitMessage();
            if (!lastMessage.includes("Gemini Swarm")) {
                const selection = await vscode.window.showErrorMessage(
                    `⚠️ Danger: The last commit "${lastMessage.trim()}" does not look like it was made by Gemini Swarm. Are you sure you want to revert it?`,
                    { modal: true },
                    "Yes, Force Revert", "Cancel"
                );
                
                if (selection !== "Yes, Force Revert") return;
            }

            await this._gitManager.undoLastCommit();
        } else {
            vscode.window.showErrorMessage("Undo is only available in Git repositories.");
        }
    }
}
