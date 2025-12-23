import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

export class ActionManager {
    private static _terminal: vscode.Terminal | undefined;

    public async insertCode(editor: vscode.TextEditor, code: string) {
        await editor.edit(editBuilder => {
            if (!editor.selection.isEmpty) {
                editBuilder.replace(editor.selection, code);
            } else {
                editBuilder.insert(editor.selection.active, code);
            }
        });
        await vscode.commands.executeCommand('editor.action.formatDocument');
    }

    public async previewDiff(document: vscode.TextDocument, newContent: string) {
        const fileName = path.basename(document.fileName);
        const tempUri = vscode.Uri.file(path.join(os.tmpdir(), `gemini_diff_${fileName}`));
        
        await fs.promises.writeFile(tempUri.fsPath, newContent);

        await vscode.commands.executeCommand(
            'vscode.diff',
            document.uri,
            tempUri,
            `Gemini Suggestion ↔ ${fileName}`
        );
    }

    /**
     * [Security Fix] 执行命令前增加用户确认
     */
    public async runInTerminal(command: string) {
        // 安全弹窗
        const selection = await vscode.window.showWarningMessage(
            `Gemini Swarm wants to run: "${command}". Allow?`,
            { modal: true },
            "Run", "Cancel"
        );

        if (selection !== "Run") {
            return;
        }

        if (!ActionManager._terminal || ActionManager._terminal.exitStatus !== undefined) {
            ActionManager._terminal = vscode.window.createTerminal({
                name: "Gemini Swarm Terminal",
                iconPath: new vscode.ThemeIcon("robot")
            });
        }
        
        ActionManager._terminal.show();
        ActionManager._terminal.sendText(command);
    }

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
