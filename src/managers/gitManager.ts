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
     * 执行 Git 命令的通用包装器
     */
    private async exec(args: string[]): Promise<string> {
        if (!this.rootPath) return "";
        
        return new Promise((resolve, reject) => {
            cp.exec(`git ${args.join(' ')}`, { cwd: this.rootPath }, (err, stdout, stderr) => {
                if (err) {
                    this.outputChannel.appendLine(`[Git Error] ${stderr}`);
                    // 不因为 git 失败而阻塞流程，只是记录日志并返回空，避免插件崩溃
                    // 除非是致命错误，否则 resolve
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
     * 策略：将当前所有未提交的修改（脏状态）暂存并提交，作为"Pre-Gemini Checkpoint"
     */
    public async createCheckpoint(message: string = "Gemini Swarm: Auto-Checkpoint"): Promise<boolean> {
        if (!await this.isGitRepo()) return false;

        // 1. 检查是否有未提交的更改
        const status = await this.exec(['status', '--porcelain']);
        if (!status) {
            // 工作区是干净的，不需要 Checkpoint，或者已经是 Commit 状态
            // 但为了保证能回滚，我们通常期望在 AI 修改前，工作区是 clean 的。
            // 如果不 clean，Aider 的做法是先把用户的脏代码 commit 掉。
            return true;
        }

        this.outputChannel.appendLine(`[Checkpoint] Saving dirty state...`);
        
        // 2. 添加所有更改
        await this.exec(['add', '.']);
        
        // 3. 提交
        await this.exec(['commit', '-m', `"${message}"`]);
        
        vscode.window.setStatusBarMessage('$(git-commit) Gemini Checkpoint Created', 3000);
        return true;
    }

    /**
     * [Undo] 回滚上一次提交 (危险操作，需谨慎)
     * 相当于 Aider 的 /undo
     */
    public async undoLastCommit() {
        if (!await this.isGitRepo()) {
            vscode.window.showErrorMessage('Not a git repository!');
            return;
        }

        // 确认回滚
        const selection = await vscode.window.showWarningMessage(
            "⚠️ Undo last commit? This will perform 'git reset --hard HEAD~1'. All changes in the last commit will be lost.",
            "Yes, Undo", "Cancel"
        );

        if (selection !== "Yes, Undo") return;

        await this.exec(['reset', '--hard', 'HEAD~1']);
        vscode.window.showInformationMessage('⏪ Changes Reverted (Time Travel Successful)');
    }
}
