import * as cp from 'child_process';
import * as vscode from 'vscode';

export class DockerHealthCheck {
    
    public async checkDockerAvailability(): Promise<boolean> {
        const config = vscode.workspace.getConfiguration('geminiSwarm');
        if (config.get<boolean>('suppressDockerWarning')) {
            return false;
        }

        return new Promise((resolve) => {
            // [Security Fix] Use spawn instead of exec to prevent shell injection (though low risk here)
            const proc = cp.spawn('docker', ['info']);
            
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
