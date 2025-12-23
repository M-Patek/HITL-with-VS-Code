import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as net from 'net'; 

export class ProcessManager {
    private serverProcess: cp.ChildProcess | undefined;
    private outputChannel: vscode.OutputChannel;
    private isRunning: boolean = false;

    constructor() {
        this.outputChannel = vscode.window.createOutputChannel("Gemini Swarm Engine");
    }

    // 自动查找可用端口
    private async findAvailablePort(startPort: number): Promise<number> {
        return new Promise((resolve, reject) => {
            const server = net.createServer();
            server.unref();
            server.on('error', () => {
                // 端口被占用，尝试下一个
                resolve(this.findAvailablePort(startPort + 1));
            });
            server.listen(startPort, () => {
                server.close(() => {
                    resolve(startPort);
                });
            });
        });
    }

    // [Optimization] 智能检测 Python 解释器
    private async resolvePythonPath(configPath: string): Promise<string> {
        // 如果用户明确指定了路径，直接使用
        if (configPath && configPath !== 'python') {
            return configPath;
        }

        // 尝试探测 python3
        return new Promise((resolve) => {
            cp.exec('python3 --version', (err) => {
                if (!err) {
                    resolve('python3');
                } else {
                    // Fallback to 'python' (可能是 Python 2 或 3，视系统而定)
                    resolve('python');
                }
            });
        });
    }

    public async start(context: vscode.ExtensionContext): Promise<boolean> {
        if (this.isRunning) {
            vscode.window.showInformationMessage('Gemini Engine is already running! 🚀');
            return true;
        }

        const config = vscode.workspace.getConfiguration('geminiSwarm');
        const userPythonPath = config.get<string>('pythonPath') || 'python';
        const apiKey = config.get<string>('apiKey');
        const configuredPort = config.get<number>('serverPort') || 8000;
        const pineconeKey = config.get<string>('pineconeKey') || '';

        if (!apiKey) {
            vscode.window.showErrorMessage('Please set geminiSwarm.apiKey in settings first! 🔑');
            return false;
        }

        // [Performance Fix] 智能解析 Python 路径
        const pythonPath = await this.resolvePythonPath(userPythonPath);
        
        // [Optimization] 自动检测端口，但不再写入 settings.json 造成副作用
        const port = await this.findAvailablePort(configuredPort);
        
        // 即使端口变了，我们也不更新配置，而是只在当前会话中使用新端口
        // 前端 Webview 会通过 'init' 消息接收这个动态端口
        if (port !== configuredPort) {
            this.outputChannel.appendLine(`[Info] Port ${configuredPort} is busy. Switched to dynamic port ${port}.`);
        }

        const scriptPath = context.asAbsolutePath(path.join('python_backend', 'api_server.py'));
        const cwd = path.dirname(scriptPath);

        this.outputChannel.appendLine(`[Boot] Starting Engine at port ${port}...`);
        this.outputChannel.appendLine(`[Boot] Python: ${pythonPath}`);
        this.outputChannel.appendLine(`[Boot] Script: ${scriptPath}`);

        try {
            // [Security Fix] 使用 JSON.stringify 安全地序列化 API Key 列表
            const safeApiKeys = JSON.stringify([apiKey]);

            // [Persistence] 传递数据目录路径
            const dataDir = context.globalStorageUri.fsPath;

            this.serverProcess = cp.spawn(pythonPath, [scriptPath], {
                cwd: cwd,
                env: {
                    ...process.env,
                    PORT: port.toString(),
                    GEMINI_API_KEYS: safeApiKeys,
                    PINECONE_API_KEY: pineconeKey,
                    SWARM_DATA_DIR: dataDir, // 传入持久化路径
                    PYTHONUNBUFFERED: '1'
                }
            });

            this.serverProcess.stdout?.on('data', (data) => {
                const msg = data.toString();
                this.outputChannel.append(`[INFO] ${msg}`);
                if (msg.includes("Engine starting on port")) {
                     vscode.window.showInformationMessage(`Gemini Engine Active on Port ${port} 🧠`);
                }
            });

            this.serverProcess.stderr?.on('data', (data) => {
                this.outputChannel.append(`[ERR] ${data.toString()}`);
            });

            this.serverProcess.on('error', (err) => {
                this.outputChannel.appendLine(`[FATAL] Failed to spawn: ${err.message}`);
                vscode.window.showErrorMessage(`Failed to start Python engine: ${err.message}`);
                this.isRunning = false;
            });

            this.serverProcess.on('close', (code) => {
                this.outputChannel.appendLine(`[STOP] Engine exited with code ${code}`);
                this.isRunning = false;
                this.serverProcess = undefined;
            });

            this.isRunning = true;
            return true;

        } catch (error: any) {
            vscode.window.showErrorMessage(`Engine Error: ${error.message}`);
            return false;
        }
    }

    public stop() {
        if (this.serverProcess) {
            this.outputChannel.appendLine('[Command] Stopping Engine...');
            this.serverProcess.kill();
            this.serverProcess = undefined;
            this.isRunning = false;
            vscode.window.showInformationMessage('Gemini Engine Stopped. 💤');
        }
    }

    public dispose() {
        this.stop();
        this.outputChannel.dispose();
    }
}
