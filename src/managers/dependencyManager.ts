import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

export class DependencyManager implements vscode.Disposable {
    private outputChannel: vscode.OutputChannel;

    constructor() {
        this.outputChannel = vscode.window.createOutputChannel("Gemini Installer");
    }

    // [Resource Fix] 释放 OutputChannel
    public dispose() {
        this.outputChannel.dispose();
    }

    public async installDependencies(context: vscode.ExtensionContext) {
        const backendPath = context.asAbsolutePath(path.join('python_backend'));
        
        // [Robustness] 探测系统 Python
        const pythonCommand = await this.detectSystemPython();
        if (!pythonCommand) {
             vscode.window.showErrorMessage("❌ Python not found! Please install Python 3.10+.");
             return;
        }

        const venvPath = path.join(backendPath, 'venv');
        const isWin = process.platform === 'win32';
        const venvPython = isWin ? path.join(venvPath, 'Scripts', 'python.exe') : path.join(venvPath, 'bin', 'python');
        
        // 尝试创建 venv
        if (!fs.existsSync(venvPython)) {
            try {
                await this.createVenv(backendPath, pythonCommand);
            } catch (e) {
                // 如果创建一半失败，清理目录防止脏数据
                try { fs.rmSync(venvPath, { recursive: true, force: true }); } catch {}
                return;
            }
        }

        // 安装依赖
        await this.installRequirements(venvPython, backendPath);
        
        // 更新设置
        const config = vscode.workspace.getConfiguration('geminiSwarm');
        await config.update('pythonPath', venvPython, vscode.ConfigurationTarget.Workspace);
        vscode.window.showInformationMessage(`✅ Python Environment Configured: ${venvPython}`);
    }

    private async detectSystemPython(): Promise<string | null> {
        // 尝试探测 python3 和 python
        const candidates = process.platform === 'win32' ? ['python', 'python3'] : ['python3', 'python'];
        for (const cmd of candidates) {
            try {
                await new Promise((resolve, reject) => {
                    cp.exec(`${cmd} --version`, (err) => err ? reject(err) : resolve(true));
                });
                return cmd;
            } catch {}
        }
        return null;
    }

    private async createVenv(cwd: string, pythonCmd: string) {
        this.outputChannel.appendLine(`[Installer] Creating venv using ${pythonCmd}...`);
        
        return new Promise<void>((resolve, reject) => {
            const venvProcess = cp.spawn(pythonCmd, ['-m', 'venv', 'venv'], { cwd });

            venvProcess.stderr.on('data', (d) => this.outputChannel.append(`[Venv] ${d}`));

            venvProcess.on('close', (code) => {
                if (code === 0) {
                    this.outputChannel.appendLine('[Installer] Venv created.');
                    resolve();
                } else {
                    const msg = `Failed to create venv (Code ${code})`;
                    this.outputChannel.appendLine(msg);
                    vscode.window.showErrorMessage(msg);
                    reject(new Error(msg));
                }
            });
        });
    }

    private async installRequirements(pythonBin: string, cwd: string) {
        const reqPath = path.join(cwd, 'requirements.txt');
        // [Robustness] 预检 requirements.txt
        if (!fs.existsSync(reqPath)) {
            vscode.window.showErrorMessage("❌ requirements.txt missing!");
            throw new Error("requirements.txt missing");
        }

        this.outputChannel.show();
        this.outputChannel.appendLine(`[Installer] Installing deps...`);

        return new Promise<void>((resolve, reject) => {
            const args = ['-m', 'pip', 'install', '-r', 'requirements.txt'];
            const proc = cp.spawn(pythonBin, args, { cwd });

            proc.stdout.on('data', d => this.outputChannel.append(`${d}`));
            proc.stderr.on('data', d => this.outputChannel.append(`${d}`));

            proc.on('close', (code) => {
                if (code === 0) {
                    resolve();
                } else {
                    vscode.window.showErrorMessage("❌ Pip install failed. Check output.");
                    reject(new Error(`Pip failed code ${code}`));
                }
            });
        });
    }
}
