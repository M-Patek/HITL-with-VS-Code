import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';

export class GitManager {
    private rootPath: string | undefined;
    private outputChannel: vscode.OutputChannel;

    constructor() {
        this.outputChannel = vscode.window.createOutputChannel("Gemini Git Ops");
        if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
            this.rootPath = vscode.workspace.workspaceFolders[0].uri.fsPath;
        }
    }

    private async exec(args: string[]): Promise<string> {
        if (!this.rootPath) return "";
        return new Promise((resolve, reject) => {
            const gitProcess = cp.spawn('git', args, { 
                cwd: this.rootPath,
                env: process.env 
            });
            let stdout = '';
            let stderr = '';
            gitProcess.stdout.on('data', (d) => stdout += d.toString());
            gitProcess.stderr.on('data', (d) => stderr += d.toString());
            gitProcess.on('close', (code) => {
                if (code !== 0) resolve(""); 
                else resolve(stdout.trim());
            });
        });
    }

    public async isGitRepo(): Promise<boolean> {
        const result = await this.exec(['rev-parse', '--is-inside-work-tree']);
        return result === 'true';
    }

    public async getLastCommitMessage(): Promise<string> {
        if (!await this.isGitRepo()) return "";
        return await this.exec(['log', '-1', '--pretty=%B']);
    }

    public async createCheckpoint(message: string = "Gemini Swarm: Auto-Checkpoint"): Promise<boolean> {
        if (!await this.isGitRepo()) return false;
        const status = await this.exec(['status', '--porcelain']);
        if (!status) return true;

        this.outputChannel.appendLine(`[Checkpoint] Saving dirty state...`);
        await this.exec(['add', '.']);
        await this.exec(['commit', '-m', message]);
        vscode.window.setStatusBarMessage('$(git-commit) Gemini Checkpoint Created', 3000);
        return true;
    }

    public async undoLastCommit() {
        if (!await this.isGitRepo()) {
            vscode.window.showErrorMessage('Not a git repository!');
            return;
        }
        await this.exec(['reset', '--hard', 'HEAD~1']);
        vscode.window.showInformationMessage('⏪ Changes Reverted');
    }

    /**
     * [Phase 3 Upgrade] Semantic Commit
     */
    public async doSemanticCommit(message: string) {
        if (!await this.isGitRepo()) {
            vscode.window.showErrorMessage("Cannot commit: Not a git repository.");
            return;
        }

        const status = await this.exec(['status', '--porcelain']);
        if (!status) {
            vscode.window.showInformationMessage("Nothing to commit.");
            return;
        }

        // Add all changes
        await this.exec(['add', '.']);
        
        // Commit with the AI generated message
        await this.exec(['commit', '-m', message]);
        
        vscode.window.showInformationMessage(`✅ Semantic Commit: ${message}`);
        this.outputChannel.appendLine(`[Semantic Commit] ${message}`);
    }
}
