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

    /**
     * [Security Fix] 使用 spawn 替代 exec 以防止 Shell 注入
     * 参数必须作为数组传递，严禁字符串拼接
     */
    private async exec(args: string[]): Promise<string> {
        if (!this.rootPath) return "";
        
        return new Promise((resolve, reject) => {
            // 使用 spawn，shell: false (默认)
            const gitProcess = cp.spawn('git', args, { 
                cwd: this.rootPath,
                env: process.env // 传递环境变量
            });

            let stdout = '';
            let stderr = '';

            gitProcess.stdout.on('data', (data) => {
                stdout += data.toString();
            });

            gitProcess.stderr.on('data', (data) => {
                stderr += data.toString();
            });

            gitProcess.on('error', (err) => {
                this.outputChannel.appendLine(`[Git Error] Spawn failed: ${err.message}`);
                resolve(""); // 保持原有的非阻塞行为
            });

            gitProcess.on('close', (code) => {
                if (code !== 0) {
                    this.outputChannel.appendLine(`[Git Error] Process exited with code ${code}: ${stderr}`);
                    resolve("");
                } else {
                    resolve(stdout.trim());
                }
            });
        });
    }

    /**
     * 检查当前是否在 Git 仓库中
     */
    public async isGitRepo(): Promise<boolean> {
        const result = await this.exec(['rev-parse', '--is-inside-work-tree']);
        return result === 'true';
    }

    /**
     * [Aider Soul] 创建修改前的“后悔药” (Auto-Commit)
     */
    public async createCheckpoint(message: string = "Gemini Swarm: Auto-Checkpoint"): Promise<boolean> {
        if (!await this.isGitRepo()) return false;

        // 1. 检查是否有未提交的更改
        const status = await this.exec(['status', '--porcelain']);
        if (!status) {
            return true;
        }

        this.outputChannel.appendLine(`[Checkpoint] Saving dirty state...`);
        
        // 2. 添加所有更改
        await this.exec(['add', '.']);
        
        // 3. 提交 (参数分离，防止注入)
        await this.exec(['commit', '-m', message]);
        
        vscode.window.setStatusBarMessage('$(git-commit) Gemini Checkpoint Created', 3000);
        return true;
    }

    /**
     * [Undo] 回滚上一次提交
     */
    public async undoLastCommit() {
        if (!await this.isGitRepo()) {
            vscode.window.showErrorMessage('Not a git repository!');
            return;
        }

        const selection = await vscode.window.showWarningMessage(
            "⚠️ Undo last commit? This will perform 'git reset --hard HEAD~1'. All changes in the last commit will be lost.",
            "Yes, Undo", "Cancel"
        );

        if (selection !== "Yes, Undo") return;

        await this.exec(['reset', '--hard', 'HEAD~1']);
        vscode.window.showInformationMessage('⏪ Changes Reverted (Time Travel Successful)');
    }
}
