import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as net from 'net';
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

    /**
     * Starts the Python Backend Server.
     * Includes logic for Token Generation, Port Discovery, and Environment Injection.
     */
    public async start(context: vscode.ExtensionContext): Promise<boolean> {
        if (this.pythonProcess) {
            this.outputChannel.appendLine("Backend already running.");
            return true;
        }

        const config = vscode.workspace.getConfiguration('geminiSwarm');
        const configuredPort = config.get<number>('serverPort', 8000);
        
        try {
            // 1. Find Port
            const port = await this.findAvailablePort(configuredPort);
            this.serverPort = port;
            
            // 2. Generate Security Token
            const authToken = crypto.randomBytes(32).toString('hex');
            ProcessManager.activeToken = authToken;
            await context.globalState.update('geminiSwarmToken', authToken);

            // 3. Determine Workspace Root (Trust Anchor)
            let safeRoot = "";
            if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
                safeRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;
            } else {
                this.outputChannel.appendLine("⚠️ No workspace folder found. Some features may be limited.");
            }

            // 4. Resolve Python Path
            const pythonPath = this.getPythonPath();
            const scriptPath = context.asAbsolutePath(path.join('api_server.py'));

            // 5. Build Environment
            const env = {
                ...process.env,
                PORT: port.toString(),
                VSCODE_PID: process.pid.toString(),
                PYTHONUNBUFFERED: '1', // Ensure logs stream immediately
                GEMINI_AUTH_TOKEN: authToken, // [Security] Inject Token
                VSCODE_WORKSPACE_ROOT: safeRoot, // [Security] Inject Trusted Root
                LOG_LEVEL: 'WARNING' // [Privacy]
            };

            this.outputChannel.appendLine(`🚀 Starting Backend at localhost:${port}`);
            
            // 6. Spawn Process
            this.pythonProcess = cp.spawn(pythonPath, [scriptPath], { env });

            // 7. Handle Stdout/Stderr
            this.pythonProcess.stdout?.on('data', (data) => {
                const msg = data.toString();
                this.outputChannel.append(msg);
            });

            this.pythonProcess.stderr?.on('data', (data) => {
                const msg = data.toString();
                this.outputChannel.append(`[ERR] ${msg}`);
            });

            this.pythonProcess.on('exit', (code, signal) => {
                this.outputChannel.appendLine(`Backend exited with code ${code}, signal ${signal}`);
                this.pythonProcess = null;
                // Optional: Auto-restart logic could go here
            });

            this.pythonProcess.on('error', (err) => {
                this.outputChannel.appendLine(`Failed to spawn backend: ${err.message}`);
                vscode.window.showErrorMessage(`Gemini Swarm Backend Error: ${err.message}`);
            });

            // 8. Wait for Health Check (Simple delay for now)
            await new Promise(resolve => setTimeout(resolve, 3000));
            
            return true;

        } catch (error) {
            this.outputChannel.appendLine(`❌ Critical Error starting backend: ${error}`);
            vscode.window.showErrorMessage(`Failed to start Gemini Swarm backend: ${error}`);
            return false;
        }
    }

    public stop() {
        if (this.pythonProcess) {
            this.outputChannel.appendLine("🛑 Stopping Backend...");
            this.pythonProcess.kill('SIGTERM'); // Try graceful first
            this.pythonProcess = null;
        }
    }

    public getPort(): number | null {
        return this.serverPort;
    }

    private getPythonPath(): string {
        const configPath = vscode.workspace.getConfiguration('geminiSwarm').get<string>('pythonPath');
        if (configPath && configPath.trim().length > 0) return configPath;
        
        // Auto-detect
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
                    // Try next port
                    resolve(this.findAvailablePort(startPort + 1));
                } else {
                    reject(err);
                }
            });
        });
    }
}
