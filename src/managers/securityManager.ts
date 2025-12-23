import * as cp from 'child_process';
import * as vscode from 'vscode';

export class SecurityManager {
    /**
     * 检查 Docker 是否可用
     * 如果不可用，弹出警告，但不会阻止插件启动（降级为非沙箱模式）
     */
    public async checkDockerAvailability(): Promise<boolean> {
        return new Promise((resolve) => {
            // 执行 docker info，这是检查守护进程是否运行的最快方法
            cp.exec('docker info', (err) => {
                if (err) {
                    vscode.window.showWarningMessage(
                        '🐳 Docker 未运行！Coding Crew 的代码沙箱功能将不可用 (Mock Mode)。为了安全执行代码，请启动 Docker Desktop 喵！'
                    );
                    resolve(false);
                } else {
                    console.log('✅ Docker is running.');
                    resolve(true);
                }
            });
        });
    }
}
