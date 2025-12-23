import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';

export class DependencyManager {
    private outputChannel: vscode.OutputChannel;

    constructor() {
        this.outputChannel = vscode.window.createOutputChannel("Gemini Installer");
    }

    public async installDependencies(context: vscode.ExtensionContext) {
        const backendPath = context.asAbsolutePath(path.join('python_backend'));
        
        // [Environment] 确定 venv 路径
        const venvPath = path.join(backendPath, 'venv');
        const isWin = process.platform === 'win32';
        const pythonBin = isWin ? path.join(venvPath, 'Scripts', 'python.exe') : path.join(venvPath, 'bin', 'python');
        
        // 1. 创建 venv (如果不存在)
        if (!fs.existsSync(pythonBin)) {
            await this.createVenv(backendPath);
        }

        // 2. 安装依赖
        await this.installRequirements(pythonBin, backendPath);
        
        // 3. 自动更新插件配置，指向新的 venv python
        const config = vscode.workspace.getConfiguration('geminiSwarm');
        await config.update('pythonPath', pythonBin, vscode.ConfigurationTarget.Workspace);
        vscode.window.showInformationMessage(`✅ Python Environment Configured: ${pythonBin}`);
    }

    private async createVenv(cwd: string) {
        this.outputChannel.appendLine(`[Installer] Creating venv in ${cwd}...`);
        const sysPython = process.platform === 'win32' ? 'python' : 'python3';
        
        return new Promise<void>((resolve, reject) => {
            // [Security Fix] 使用 spawn 替代 exec
            const venvProcess = cp.spawn(sysPython, ['-m', 'venv', 'venv'], { cwd });

            venvProcess.stdout.on('data', (data) => {
                this.outputChannel.append(`[Venv] ${data}`);
            });

            venvProcess.stderr.on('data', (data) => {
                this.outputChannel.append(`[Venv Err] ${data}`);
            });

            venvProcess.on('close', (code) => {
                if (code === 0) {
                    this.outputChannel.appendLine('[Installer] Venv created.');
                    resolve();
                } else {
                    const msg = `Failed to create venv, exit code: ${code}`;
                    this.outputChannel.appendLine(`[Error] ${msg}`);
                    vscode.window.showErrorMessage('Failed to create Python virtual environment.');
                    reject(new Error(msg));
                }
            });

            venvProcess.on('error', (err) => {
                this.outputChannel.appendLine(`[Error] Spawn failed: ${err.message}`);
                reject(err);
            });
        });
    }

    private async installRequirements(pythonBin: string, cwd: string) {
        this.outputChannel.show();
        this.outputChannel.appendLine(`[Installer] Installing requirements using ${pythonBin}...`);

        return new Promise<void>((resolve, reject) => {
            // spawn 已经是安全的数组传参
            const args = ['-m', 'pip', 'install', '-r', 'requirements.txt'];
            const proc = cp.spawn(pythonBin, args, { cwd });

            proc.stdout.on('data', d => this.outputChannel.append(`[PIP] ${d}`));
            proc.stderr.on('data', d => this.outputChannel.append(`[PIP ERR] ${d}`));

            proc.on('close', (code) => {
                if (code === 0) {
                    vscode.window.showInformationMessage("✅ Dependencies installed successfully in venv!");
                    resolve();
                } else {
                    reject(new Error(`Pip failed with code ${code}`));
                }
            });
        });
    }
}
