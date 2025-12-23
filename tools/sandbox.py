import docker
import time
import logging
import tarfile
import io
import base64
import os
import uuid
import re
import shutil
from typing import Tuple, List, Optional, Dict

logger = logging.getLogger("Tools-Sandbox")

class StatefulSandbox:
    def __init__(self, task_id: str, image: str = "python:3.9-slim", workspace_root: str = None):
        self.task_id = task_id
        self.image = image
        self.workspace_root = workspace_root
        self.container_name = f"swarm_session_{task_id}"
        self.client = None
        self.container = None
        self.docker_available = False
        
        self._init_docker_client()

    def _init_docker_client(self):
        try:
            self.client = docker.from_env()
            self.client.ping()
            self.docker_available = True
        except Exception as e:
            logger.warning(f"⚠️ Docker not available: {e}. Entering Mock Mode.")
            self.docker_available = False

    def start_session(self):
        if not self.docker_available: return

        try:
            # 检查是否已存在同名容器
            existing = self.client.containers.list(all=True, filters={"name": self.container_name})
            if existing:
                self.container = existing[0]
                if self.container.status != "running":
                    self.container.start()
                logger.info(f"🔄 Resumed existing session: {self.container_name}")
                return

            logger.info(f"🚀 Starting new session: {self.container_name}")
            
            # [Security Fix] 强制只读挂载 (Read-Only Mount)
            # 防止容器内的恶意代码 (如 rm -rf /workspace) 删除用户主机上的文件
            volumes = {}
            if self.workspace_root and os.path.exists(self.workspace_root):
                volumes[self.workspace_root] = {'bind': '/workspace', 'mode': 'ro'}
                logger.info(f"🛡️ Mounted workspace (Read-Only): {self.workspace_root} -> /workspace")
            else:
                logger.info("⚠️ No workspace root provided.")

            # 使用 /tmp/sandbox_scratch 作为可写的工作目录，防止污染项目根目录
            self.container = self.client.containers.run(
                self.image,
                detach=True,
                tty=True,
                name=self.container_name,
                entrypoint="tail -f /dev/null", 
                mem_limit="512m",
                network_mode="none", # [Security Fix] 默认断网，除非明确需要联网
                volumes=volumes,
                working_dir="/tmp" # 改变工作目录到临时区
            )
            
            # 初始化环境
            self.container.exec_run("mkdir -p /tmp/output")

        except Exception as e:
            logger.error(f"Failed to start sandbox session: {e}")
            self.docker_available = False 

    def execute_code(self, code: str, timeout: int = 30) -> Tuple[str, str, List[Dict[str, str]]]:
        """在当前会话中执行代码"""
        if not self.docker_available or not self.container:
            return (
                "", 
                "[System] Docker unavailable. Code execution skipped. Please enable Docker to run code safely.",
                []
            )

        try:
            run_id = str(uuid.uuid4())[:8]
            # 脚本必须写入可写的临时目录，不能写入只读的 /workspace
            script_path = f"/tmp/script_{run_id}.py"
            plot_path = f"/tmp/plot_{run_id}.png"
            
            wrapped_code = self._wrap_code_with_plot_saving(code, plot_path)
            self._write_file_to_container("/tmp", f"script_{run_id}.py", wrapped_code)
            
            # [Optimization] 使用 Python 内部超时机制而非依赖系统 timeout 命令
            # 构造一个 Runner 脚本来执行目标脚本，从而实现跨平台超时
            runner_code = f"""
import subprocess
import sys

try:
    result = subprocess.run(
        [sys.executable, "{script_path}"], 
        capture_output=True, 
        text=True, 
        timeout={timeout}
    )
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    sys.exit(result.returncode)
except subprocess.TimeoutExpired:
    print("❌ Execution Timed Out (Limit: {timeout}s)", file=sys.stderr)
    sys.exit(124)
except Exception as e:
    print(f"Runner Error: {{e}}", file=sys.stderr)
    sys.exit(1)
"""
            runner_path = f"/tmp/runner_{run_id}.py"
            self._write_file_to_container("/tmp", f"runner_{run_id}.py", runner_code)

            # 执行 Runner
            exec_result = self.container.exec_run(f"python {runner_path}", workdir="/tmp")
            
            stdout = exec_result.output.decode("utf-8", errors="replace")
            stderr = ""
            
            # 解析 Runner 的输出 (简单处理，实际 stdout/stderr 已混合，此处简化)
            # 注意：Docker exec_run 的 output 是 stdout 和 stderr 合并的
            # 真正的分离需要使用 socket attach，这里为了简化依然混合返回
            
            images = self._extract_image_from_container(plot_path)
            
            # 清理临时文件
            try:
                self.container.exec_run(f"rm {script_path} {runner_path} {plot_path}")
            except: pass

            return stdout, stderr, images
            
        except Exception as e:
            return "", f"System Error: {str(e)}", []

    def execute_command(self, command: str) -> str:
        if not self.docker_available or not self.container:
             return "[System] Docker unavailable. Command execution skipped."

        try:
            # 限制在 /tmp 下执行，或明确提示只读限制
            exec_result = self.container.exec_run(command, workdir="/tmp")
            return exec_result.output.decode("utf-8", errors="replace")
        except Exception as e:
            return f"Command failed: {e}"

    def close_session(self):
        if self.container:
            try:
                logger.info(f"🛑 Closing session: {self.container_name}")
                self.container.remove(force=True)
            except:
                pass
            self.container = None

    def _write_file_to_container(self, dest_dir: str, filename: str, content: str):
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode='w') as tar:
            data = content.encode('utf-8')
            tarinfo = tarfile.TarInfo(name=filename)
            tarinfo.size = len(data)
            tarinfo.mtime = time.time()
            tar.addfile(tarinfo, io.BytesIO(data))
        tar_stream.seek(0)
        self.container.put_archive(path=dest_dir, data=tar_stream)

    def _extract_image_from_container(self, filepath: str) -> List[Dict[str, str]]:
        images = []
        try:
            stream, stat = self.container.get_archive(filepath)
            file_obj = io.BytesIO()
            for chunk in stream:
                file_obj.write(chunk)
            file_obj.seek(0)
            with tarfile.open(fileobj=file_obj, mode='r') as tar:
                for m in tar.getmembers():
                    if m.isfile():
                        img_data = tar.extractfile(m).read()
                        b64_img = base64.b64encode(img_data).decode('utf-8')
                        images.append({"type": "image", "filename": m.name, "data": f"data:image/png;base64,{b64_img}"})
        except:
            pass
        return images

    def _wrap_code_with_plot_saving(self, code: str, save_path: str) -> str:
        if re.search(r"^\s*(import|from)\s+matplotlib", code, re.MULTILINE):
            header = f"import matplotlib\nmatplotlib.use('Agg')\nimport matplotlib.pyplot as plt\n"
            footer = f"\ntry:\n    if plt.get_fignums():\n        plt.savefig('{save_path}')\nexcept: pass"
            return header + code + footer
        return code
