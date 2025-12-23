import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';

export class GitManager implements vscode.Disposable {
    private rootPath: string | undefined;
    private outputChannel: vscode.OutputChannel;

    constructor() {
        this.outputChannel = vscode.window.createOutputChannel("Gemini Git Ops");
        if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
            this.rootPath = vscode.workspace.workspaceFolders[0].uri.fsPath;
        }
    }

    public dispose() {
        this.outputChannel.dispose();
    }

    private async exec(args: string[]): Promise<{ stdout: string, stderr: string, code: number }> {
        if (!this.rootPath) return { stdout: "", stderr: "No workspace root", code: -1 };
        
        return new Promise((resolve) => {
            const gitProcess = cp.spawn('git', args, { 
                cwd: this.rootPath,
                env: process.env 
            });
            let stdout = '';
            let stderr = '';
            gitProcess.stdout.on('data', (d) => stdout += d.toString());
            gitProcess.stderr.on('data', (d) => stderr += d.toString());
            gitProcess.on('close', (code) => {
                resolve({ stdout: stdout.trim(), stderr: stderr.trim(), code: code ?? -1 });
            });
        });
    }

    public async isGitRepo(): Promise<boolean> {
        const result = await this.exec(['rev-parse', '--is-inside-work-tree']);
        return result.stdout === 'true' && result.code === 0;
    }

    public async getLastCommitMessage(): Promise<string> {
        if (!await this.isGitRepo()) return "";
        const res = await this.exec(['log', '-1', '--pretty=%B']);
        return res.stdout;
    }

    public async createCheckpoint(message: string = "Gemini Swarm: Auto-Checkpoint"): Promise<boolean> {
        if (!await this.isGitRepo()) return false;
        
        // 检查状态
        const statusRes = await this.exec(['status', '--porcelain']);
        if (statusRes.code !== 0) {
             this.outputChannel.appendLine(`[Checkpoint Error] git status failed: ${statusRes.stderr}`);
             return false;
        }
        if (!statusRes.stdout) return true; // Clean

        this.outputChannel.appendLine(`[Checkpoint] Saving dirty state...`);
        await this.exec(['add', '.']);
        const commitRes = await this.exec(['commit', '-m', message]);
        
        if (commitRes.code === 0) {
            vscode.window.setStatusBarMessage('$(git-commit) Gemini Checkpoint Created', 3000);
            return true;
        } else {
             this.outputChannel.appendLine(`[Checkpoint Error] Commit failed: ${commitRes.stderr}`);
             return false;
        }
    }

    public async undoLastCommit() {
        if (!await this.isGitRepo()) {
            vscode.window.showErrorMessage('Not a git repository!');
            return;
        }

        // [Security Fix] 防止数据丢失：检查工作区是否脏
        const statusRes = await this.exec(['status', '--porcelain']);
        if (statusRes.code !== 0) {
            vscode.window.showErrorMessage('Git status check failed. Aborting undo.');
            return;
        }

        if (statusRes.stdout.length > 0) {
            vscode.window.showErrorMessage(
                '❌ Undo Aborted: You have uncommitted changes. Resetting now would lose your work. Please commit or stash them first.'
            );
            return;
        }

        const res = await this.exec(['reset', '--hard', 'HEAD~1']);
        if (res.code === 0) {
            vscode.window.showInformationMessage('⏪ Changes Reverted');
        } else {
            vscode.window.showErrorMessage(`Undo Failed: ${res.stderr}`);
        }
    }

    public async doSemanticCommit(message: string) {
        if (!await this.isGitRepo()) {
            vscode.window.showErrorMessage("Cannot commit: Not a git repository.");
            return;
        }

        const statusRes = await this.exec(['status', '--porcelain']);
        if (!statusRes.stdout) {
            vscode.window.showInformationMessage("Nothing to commit.");
            return;
        }

        await this.exec(['add', '.']);
        const res = await this.exec(['commit', '-m', message]);
        
        if (res.code === 0) {
            vscode.window.showInformationMessage(`✅ Semantic Commit: ${message}`);
            this.outputChannel.appendLine(`[Semantic Commit] ${message}`);
        } else {
            vscode.window.showErrorMessage(`Commit Failed: ${res.stderr}`);
        }
    }
}
