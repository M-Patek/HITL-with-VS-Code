import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as net from 'net';
import * as os from 'os';
import * as crypto from 'crypto'; 

export class ProcessManager {
    private static instance: ProcessManager;
    private pythonProcess: cp.ChildProcess | null = null;
    private serverPort: number | null = null;
    private readonly outputChannel: vscode.OutputChannel;
    private static activeToken: string = "";

    private constructor() {
        this.outputChannel = vscode.window.createOutputChannel("Gemini Swarm Backend");
    }

    public static getInstance(): ProcessManager {
        if (!ProcessManager.instance) {
            ProcessManager.instance = new ProcessManager();
        }
        return ProcessManager.instance;
    }

    public static getActiveToken(): string {
        return ProcessManager.activeToken;
    }

    public async start(context: vscode.ExtensionContext): Promise<boolean> {
        if (this.pythonProcess) {
            return true;
        }

        const configuredPort = vscode.workspace.getConfiguration('geminiSwarm').get<number>('serverPort', 8000);
        
        try {
            const port = await this.findAvailablePort(configuredPort);
            this.serverPort = port;
            
            // [Security] Generate a strong random token for API authentication
            const authToken = crypto.randomBytes(32).toString('hex');
            ProcessManager.activeToken = authToken;
            
            // Save token for persistence
            await context.globalState.update('geminiSwarmToken', authToken);

            // [Security] Get Trusted Workspace Root
            let safeRoot = "";
            if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
                safeRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;
            }

            const pythonPath = this.getPythonPath();
            const scriptPath = context.asAbsolutePath(path.join('api_server.py'));

            const env = {
                ...process.env,
                PORT: port.toString(),
                VSCODE_PID: process.pid.toString(),
                PYTHONUNBUFFERED: '1',
                GEMINI_AUTH_TOKEN: authToken, // [Fix] Inject Token
                VSCODE_WORKSPACE_ROOT: safeRoot, // [Fix] Inject Safe Root
                LOG_LEVEL: 'WARNING' // [Fix] Privacy
            };

            this.outputChannel.appendLine(`🚀 Starting Backend on port ${port}...`);
            this.pythonProcess = cp.spawn(pythonPath, [scriptPath], { env });

            this.pythonProcess.stdout?.on('data', (data) => {
                this.outputChannel.append(`[Backend]: ${data}`);
            });

            this.pythonProcess.stderr?.on('data', (data) => {
                this.outputChannel.append(`[Backend Error]: ${data}`);
            });

            this.pythonProcess.on('exit', (code) => {
                this.outputChannel.appendLine(`Backend exited with code ${code}`);
                this.pythonProcess = null;
            });

            // Wait for server to be ready
            await new Promise(resolve => setTimeout(resolve, 2000));
            return true;

        } catch (error) {
            this.outputChannel.appendLine(`❌ Failed to start backend: ${error}`);
            vscode.window.showErrorMessage(`Failed to start Gemini Swarm backend: ${error}`);
            return false;
        }
    }

    public stop() {
        if (this.pythonProcess) {
            this.pythonProcess.kill();
            this.pythonProcess = null;
            this.outputChannel.appendLine("🛑 Backend stopped.");
        }
    }

    public getPort(): number | null {
        return this.serverPort;
    }

    private getPythonPath(): string {
        const configPath = vscode.workspace.getConfiguration('geminiSwarm').get<string>('pythonPath');
        if (configPath) return configPath;
        return process.platform === 'win32' ? 'python' : 'python3';
    }

    private findAvailablePort(startPort: number): Promise<number> {
        return new Promise((resolve, reject) => {
            const server = net.createServer();
            server.listen(startPort, () => {
                const { port } = server.address() as net.AddressInfo;
                server.close(() => resolve(port));
            });
            server.on('error', (err: any) => {
                if (err.code === 'EADDRINUSE') {
                    resolve(this.findAvailablePort(startPort + 1));
                } else {
                    reject(err);
                }
            });
        });
    }
}
