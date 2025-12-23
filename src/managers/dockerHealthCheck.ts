import * as cp from 'child_process';
import * as vscode from 'vscode';

// [Renamed] "SecurityManager" 名不副实，更名为 DockerHealthCheck
export class DockerHealthCheck {
    
    public async checkDockerAvailability(): Promise<boolean> {
        const config = vscode.workspace.getConfiguration('geminiSwarm');
        if (config.get<boolean>('suppressDockerWarning')) {
            return false;
        }

        return new Promise((resolve) => {
            // [Security Fix] 使用 spawn 替代 exec
            const proc = cp.spawn('docker', ['info']);
            
            // 超时控制，防止挂起
            const timer = setTimeout(() => {
                proc.kill();
                resolve(false);
            }, 5000);

            proc.on('close', (code) => {
                clearTimeout(timer);
                if (code !== 0) {
                    vscode.window.showWarningMessage(
                        '🐳 Docker not detected. Swarm running in Mock Mode.',
                        "Don't show again"
                    ).then(sel => {
                        if (sel === "Don't show again") {
                            config.update('suppressDockerWarning', true, vscode.ConfigurationTarget.Global);
                        }
                    });
                    resolve(false);
                } else {
                    resolve(true);
                }
            });

            proc.on('error', () => {
                clearTimeout(timer);
                resolve(false);
            });
        });
    }
}
