import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

export class DependencyManager {
    private outputChannel: vscode.OutputChannel;

    constructor() {
        this.outputChannel = vscode.window.createOutputChannel("Gemini Installer");
    }

    public async installDependencies(context: vscode.ExtensionContext) {
        const config = vscode.workspace.getConfiguration('geminiSwarm');
        
        // [Optimization] 智能推断 Python 命令，防止 Linux/Mac 上 python2 的问题
        const defaultPython = process.platform === 'win32' ? 'python' : 'python3';
        const pythonPath = config.get<string>('pythonPath') || defaultPython;
        
        let backendPath = context.asAbsolutePath(path.join('python_backend'));
        
        if (!fs.existsSync(backendPath)) {
            if (fs.existsSync(context.asAbsolutePath('requirements.txt'))) {
                backendPath = context.extensionPath;
            } else {
                vscode.window.showErrorMessage(`❌ 找不到 python_backend 目录或 requirements.txt 喵！路径: ${backendPath}`);
                return;
            }
        }

        const requirementsFile = path.join(backendPath, 'requirements.txt');

        this.outputChannel.show();
        this.outputChannel.appendLine(`[Installer] Target: ${requirementsFile}`);
        this.outputChannel.appendLine(`[Installer] Python: ${pythonPath}`);

        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "Gemini Swarm: 正在安装 Python 依赖...",
            cancellable: false
        }, async (progress) => {
            return new Promise<void>((resolve, reject) => {
                const installProcess = cp.spawn(pythonPath, ['-m', 'pip', 'install', '-r', 'requirements.txt'], {
                    cwd: backendPath
                });

                installProcess.stdout.on('data', (data) => {
                    this.outputChannel.append(`[PIP] ${data}`);
                });

                installProcess.stderr.on('data', (data) => {
                    this.outputChannel.append(`[PIP ERR] ${data}`);
                });

                installProcess.on('close', (code) => {
                    if (code === 0) {
                        vscode.window.showInformationMessage("✅ 依赖安装成功！请重启插件引擎喵！");
                        resolve();
                    } else {
                        vscode.window.showErrorMessage(`❌ 安装失败 (Code ${code})。请检查输出面板。`);
                        reject(new Error(`Pip failed with code ${code}`));
                    }
                });
                
                installProcess.on('error', (err) => {
                     vscode.window.showErrorMessage(`❌ 无法启动 Python 进程: ${err.message}`);
                     reject(err);
                });
            });
        });
    }
}
