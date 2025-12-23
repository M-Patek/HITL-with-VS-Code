import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as net from 'net'; 

export class ProcessManager implements vscode.Disposable {
    private serverProcess: cp.ChildProcess | undefined;
    private outputChannel: vscode.OutputChannel;
    private isRunning: boolean = false;
    
    private static activePort: number = 0;

    constructor() {
        this.outputChannel = vscode.window.createOutputChannel("Gemini Swarm Engine");
    }

    public dispose() {
        this.stop();
        this.outputChannel.dispose();
    }

    public static getActivePort(): number {
        return ProcessManager.activePort;
    }

    private async findAvailablePort(startPort: number, retries = 0): Promise<number> {
        if (retries > 100) throw new Error("No available ports found after 100 retries.");

        return new Promise((resolve, reject) => {
            const server = net.createServer();
            server.unref();
            server.on('error', () => resolve(this.findAvailablePort(startPort + 1, retries + 1)));
            server.listen(startPort, () => {
                server.close(() => resolve(startPort));
            });
        });
    }

    private async resolvePythonPath(configPath: string): Promise<string> {
        if (configPath && configPath !== 'python') return configPath;
        return new Promise((resolve) => {
            const cmd = process.platform === 'win32' ? 'python' : 'python3';
            cp.exec(`${cmd} --version`, (err) => resolve(err ? 'python' : cmd));
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
        
        try {
            const port = await this.findAvailablePort(configuredPort);
            
            const scriptPath = context.asAbsolutePath(path.join('python_backend', 'api_server.py'));
            const cwd = path.dirname(scriptPath);

            this.outputChannel.appendLine(`[Boot] Starting Engine at port ${port}...`);

            const env = {
                ...process.env, 
                PORT: port.toString(),
                GEMINI_API_KEYS: JSON.stringify([apiKey]),
                PINECONE_API_KEY: pineconeKey,
                SWARM_DATA_DIR: context.globalStorageUri.fsPath,
                PYTHONUNBUFFERED: '1',
                HOST_PID: process.pid.toString() // Passed for suicide pact
            };

            // [Security Fix] detached: false ensures child process is attached to parent's lifecycle by default (on some OS)
            // But 'detached: true' + unref() is for zombies. We want the opposite.
            // Defaults are usually fine, but being explicit helps understanding.
            this.serverProcess = cp.spawn(pythonPath, [scriptPath], { 
                cwd, 
                env,
                detached: false 
            });

            this.serverProcess.stdout?.on('data', (data) => {
                const msg = data.toString();
                this.outputChannel.append(`[INFO] ${msg}`);
                if (msg.includes("Uvicorn running on")) {
                     ProcessManager.activePort = port;
                     vscode.window.showInformationMessage(`Gemini Engine Active on Port ${port} 🧠`);
                }
            });

            this.serverProcess.stderr?.on('data', (data) => this.outputChannel.append(`[ERR] ${data}`));

            this.serverProcess.on('error', (err) => {
                vscode.window.showErrorMessage(`Engine Error: ${err.message}`);
                this.isRunning = false;
                ProcessManager.activePort = 0;
            });

            this.serverProcess.on('close', (code) => {
                this.outputChannel.appendLine(`[STOP] Engine exited with code ${code}`);
                this.isRunning = false;
                ProcessManager.activePort = 0;
            });

            this.isRunning = true;
            return true;

        } catch (error: any) {
            vscode.window.showErrorMessage(`Engine Start Failed: ${error.message}`);
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
}
