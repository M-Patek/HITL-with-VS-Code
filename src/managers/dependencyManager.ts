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
        // 尝试使用系统 python 创建 venv
        const sysPython = process.platform === 'win32' ? 'python' : 'python3';
        
        return new Promise<void>((resolve, reject) => {
            cp.exec(`${sysPython} -m venv venv`, { cwd }, (err, stdout, stderr) => {
                if (err) {
                    this.outputChannel.appendLine(`[Error] Failed to create venv: ${stderr}`);
                    vscode.window.showErrorMessage('Failed to create Python virtual environment.');
                    reject(err);
                } else {
                    this.outputChannel.appendLine('[Installer] Venv created.');
                    resolve();
                }
            });
        });
    }

    private async installRequirements(pythonBin: string, cwd: string) {
        this.outputChannel.show();
        this.outputChannel.appendLine(`[Installer] Installing requirements using ${pythonBin}...`);

        return new Promise<void>((resolve, reject) => {
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
