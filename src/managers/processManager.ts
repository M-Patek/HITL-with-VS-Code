import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as net from 'net'; 

export class ProcessManager {
    private serverProcess: cp.ChildProcess | undefined;
    private outputChannel: vscode.OutputChannel;
    private isRunning: boolean = false;
    
    // [Phase 3 Upgrade] Expose active port for other providers (e.g., Completion)
    private static activePort: number = 0;

    constructor() {
        this.outputChannel = vscode.window.createOutputChannel("Gemini Swarm Engine");
    }

    public static getActivePort(): number {
        return ProcessManager.activePort;
    }

    private async findAvailablePort(startPort: number): Promise<number> {
        return new Promise((resolve, reject) => {
            const server = net.createServer();
            server.unref();
            server.on('error', () => resolve(this.findAvailablePort(startPort + 1)));
            server.listen(startPort, () => {
                server.close(() => resolve(startPort));
            });
        });
    }

    private async resolvePythonPath(configPath: string): Promise<string> {
        if (configPath && configPath !== 'python') return configPath;
        return new Promise((resolve) => {
            cp.exec('python3 --version', (err) => resolve(err ? 'python' : 'python3'));
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

        const pythonPath = await this.resolvePythonPath(userPythonPath);
        const port = await this.findAvailablePort(configuredPort);
        ProcessManager.activePort = port; // [Phase 3 Upgrade] Store port

        const scriptPath = context.asAbsolutePath(path.join('python_backend', 'api_server.py'));
        const cwd = path.dirname(scriptPath);

        this.outputChannel.appendLine(`[Boot] Starting Engine at port ${port}...`);

        try {
            const safeApiKeys = JSON.stringify([apiKey]);
            const dataDir = context.globalStorageUri.fsPath;

            this.serverProcess = cp.spawn(pythonPath, [scriptPath], {
                cwd: cwd,
                env: {
                    ...process.env,
                    PORT: port.toString(),
                    GEMINI_API_KEYS: safeApiKeys,
                    PINECONE_API_KEY: pineconeKey,
                    SWARM_DATA_DIR: dataDir,
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

            this.serverProcess.stderr?.on('data', (data) => this.outputChannel.append(`[ERR] ${data}`));

            this.serverProcess.on('error', (err) => {
                vscode.window.showErrorMessage(`Engine Error: ${err.message}`);
                this.isRunning = false;
            });

            this.serverProcess.on('close', (code) => {
                this.outputChannel.appendLine(`[STOP] Engine exited with code ${code}`);
                this.isRunning = false;
                ProcessManager.activePort = 0;
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
            this.serverProcess.kill();
            this.serverProcess = undefined;
            this.isRunning = false;
            ProcessManager.activePort = 0;
        }
    }

    public dispose() {
        this.stop();
        this.outputChannel.dispose();
    }
}
