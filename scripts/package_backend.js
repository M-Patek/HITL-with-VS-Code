const fs = require('fs');
const path = require('path');

// 需要复制的 Python 模块目录
const sourceDirs = [
    'agents',
    'config',
    'core',
    'tools',
    'workflow'
];

// 需要复制的独立文件
const sourceFiles = [
    'api_server.py',
    'requirements.txt',
    '.env.example' // 如果有的话
];

// 目标目录: dist/python_backend
const targetDir = path.join(__dirname, '../dist/python_backend');

console.log('📦 [Build] Packaging Python Backend...');
console.log(`   Target: ${targetDir}`);

// 1. 确保目标目录存在
if (!fs.existsSync(targetDir)){
    fs.mkdirSync(targetDir, { recursive: true });
}

// 辅助函数: 复制文件
function copyFile(src, dest) {
    try {
        fs.copyFileSync(src, dest);
        console.log(`   📄 Copied: ${path.basename(src)}`);
    } catch (e) {
        // 忽略可选文件缺失
        if (src.includes('.env')) return;
        console.warn(`   ⚠️ Warning: File not found ${src}`);
    }
}

// 辅助函数: 递归复制目录
function copyDir(src, dest) {
    if (!fs.existsSync(dest)){
        fs.mkdirSync(dest, { recursive: true });
    }
    
    try {
        const entries = fs.readdirSync(src, { withFileTypes: true });

        for (let entry of entries) {
            const srcPath = path.join(src, entry.name);
            const destPath = path.join(dest, entry.name);

            // 忽略 __pycache__
            if (entry.name === '__pycache__' || entry.name.endsWith('.pyc')) continue;

            if (entry.isDirectory()) {
                copyDir(srcPath, destPath);
            } else {
                fs.copyFileSync(srcPath, destPath);
            }
        }
    } catch (e) {
        console.warn(`   ⚠️ Warning: Directory not found ${src}`);
    }
}

// 2. 执行复制
sourceDirs.forEach(dir => {
    const srcPath = path.join(__dirname, '../', dir);
    copyDir(srcPath, path.join(targetDir, dir));
});

sourceFiles.forEach(file => {
    const srcPath = path.join(__dirname, '../', file);
    copyFile(srcPath, path.join(targetDir, file));
});

console.log('✅ Python Backend packaged successfully!');
