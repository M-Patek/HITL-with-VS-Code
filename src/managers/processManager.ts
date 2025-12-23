import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as net from 'net'; // [New]

export class ProcessManager {
    private serverProcess: cp.ChildProcess | undefined;
    private outputChannel: vscode.OutputChannel;
    private isRunning: boolean = false;

    constructor() {
        this.outputChannel = vscode.window.createOutputChannel("Gemini Swarm Engine");
    }

    // [New] 自动查找可用端口
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

    public async start(context: vscode.ExtensionContext): Promise<boolean> {
        if (this.isRunning) {
            vscode.window.showInformationMessage('Gemini Engine is already running! 🚀');
            return true;
        }

        const config = vscode.workspace.getConfiguration('geminiSwarm');
        // [Critical Fix] 统一使用 pythonPath，但建议用户检查是否为 python3
        const pythonPath = config.get<string>('pythonPath') || 'python';
        const apiKey = config.get<string>('apiKey');
        const configuredPort = config.get<number>('serverPort') || 8000;
        const pineconeKey = config.get<string>('pineconeKey') || '';

        if (!apiKey) {
            vscode.window.showErrorMessage('Please set geminiSwarm.apiKey in settings first! 🔑');
            return false;
        }

        // [New] 自动检测端口
        const port = await this.findAvailablePort(configuredPort);
        if (port !== configuredPort) {
            this.outputChannel.appendLine(`[Info] Port ${configuredPort} is busy. Switched to ${port}.`);
            // 更新配置，以便前端能连上正确的端口
            await config.update('serverPort', port, vscode.ConfigurationTarget.Workspace);
        }

        const scriptPath = context.asAbsolutePath(path.join('python_backend', 'api_server.py'));
        const cwd = path.dirname(scriptPath);

        this.outputChannel.appendLine(`[Boot] Starting Engine at port ${port}...`);
        this.outputChannel.appendLine(`[Boot] Python: ${pythonPath}`);
        this.outputChannel.appendLine(`[Boot] Script: ${scriptPath}`);

        try {
            this.serverProcess = cp.spawn(pythonPath, [scriptPath], {
                cwd: cwd,
                env: {
                    ...process.env,
                    PORT: port.toString(),
                    GEMINI_API_KEYS: `["${apiKey}"]`,
                    PINECONE_API_KEY: pineconeKey,
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
