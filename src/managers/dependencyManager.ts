import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

export class DependencyManager {
    private outputChannel: vscode.OutputChannel;

    constructor() {
        this.outputChannel = vscode.window.createOutputChannel("Gemini Installer");
    }

    /**
     * 执行 pip install -r requirements.txt
     */
    public async installDependencies(context: vscode.ExtensionContext) {
        const config = vscode.workspace.getConfiguration('geminiSwarm');
        const pythonPath = config.get<string>('pythonPath') || 'python';
        
        // 定位打包后的后端目录
        // 在开发环境是项目根目录，在生产环境是 dist/python_backend
        // 我们通过检测当前上下文来判断
        let backendPath = context.asAbsolutePath(path.join('python_backend'));
        
        // 如果插件根目录下没有 python_backend (开发模式可能直接在根目录)，则尝试直接用根目录
        if (!fs.existsSync(backendPath)) {
            // 回退逻辑：假设用户是在源码模式运行，且 requirements.txt 在根目录
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
