import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

export class ActionManager {
    private static _terminal: vscode.Terminal | undefined;

    /**
     * 将代码插入到当前编辑器
     * 如果有选区则替换，否则在光标处插入
     */
    public async insertCode(editor: vscode.TextEditor, code: string) {
        await editor.edit(editBuilder => {
            if (!editor.selection.isEmpty) {
                editBuilder.replace(editor.selection, code);
            } else {
                editBuilder.insert(editor.selection.active, code);
            }
        });
        // 格式化文档（可选）
        await vscode.commands.executeCommand('editor.action.formatDocument');
    }

    /**
     * 打开 Diff 视图预览变更
     * 这是一个高级功能：不直接修改文件，而是先让用户对比
     */
    public async previewDiff(document: vscode.TextDocument, newContent: string) {
        const fileName = path.basename(document.fileName);
        const tempUri = vscode.Uri.file(path.join(os.tmpdir(), `gemini_diff_${fileName}`));
        
        // 写入临时文件
        await fs.promises.writeFile(tempUri.fsPath, newContent);

        // 调用 VS Code 内置的 Diff 命令
        await vscode.commands.executeCommand(
            'vscode.diff',
            document.uri,
            tempUri,
            `Gemini Suggestion ↔ ${fileName}`
        );
    }

    /**
     * 在专用终端中执行 Shell 命令
     * 适用于: pip install, npm run test, git commit 等
     */
    public runInTerminal(command: string) {
        // 确保终端存在且未被关闭
        if (!ActionManager._terminal || ActionManager._terminal.exitStatus !== undefined) {
            ActionManager._terminal = vscode.window.createTerminal({
                name: "Gemini Swarm Terminal",
                iconPath: new vscode.ThemeIcon("robot")
            });
        }
        
        ActionManager._terminal.show();
        ActionManager._terminal.sendText(command);
    }

    /**
     * 直接替换整个文件内容 (慎用)
     */
    public async replaceFileContent(document: vscode.TextDocument, newContent: string) {
        const edit = new vscode.WorkspaceEdit();
        const fullRange = new vscode.Range(
            document.lineAt(0).range.start,
            document.lineAt(document.lineCount - 1).range.end
        );
        edit.replace(document.uri, fullRange, newContent);
        await vscode.workspace.applyEdit(edit);
    }
}
