import docker
import time
import logging
import tarfile
import io
import base64
import os
import uuid
import re
from typing import Tuple, List, Optional, Dict

logger = logging.getLogger("Tools-Sandbox")

class StatefulSandbox:
    """
    [OpenDevin Soul] 持久化沙箱
    维护一个长生命周期的 Docker 容器，支持连续的 Shell 会话和状态保持。
    """
    def __init__(self, task_id: str, image: str = "python:3.9-slim"):
        self.task_id = task_id
        self.image = image
        # 容器名与 Task ID 绑定，确保唯一且可复用
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
        """启动持久化会话容器"""
        if not self.docker_available: return

        try:
            # 检查是否已存在同名容器（可能是之前残留的）
            existing = self.client.containers.list(all=True, filters={"name": self.container_name})
            if existing:
                self.container = existing[0]
                if self.container.status != "running":
                    self.container.start()
                logger.info(f"🔄 Resumed existing session: {self.container_name}")
                return

            # 启动新容器，执行 tail -f /dev/null 保持常驻
            logger.info(f"🚀 Starting new session: {self.container_name}")
            self.container = self.client.containers.run(
                self.image,
                detach=True,
                tty=True,
                name=self.container_name,
                entrypoint="tail -f /dev/null", # [Critical] Keep alive
                mem_limit="512m",
                network_mode="bridge" # 允许联网安装包 (pip install)
            )
            
            # 初始化环境 (可选)
            self.container.exec_run("mkdir -p /workspace")

        except Exception as e:
            logger.error(f"Failed to start sandbox session: {e}")
            self.docker_available = False # Fallback

    def execute_code(self, code: str, timeout: int = 30) -> Tuple[str, str, List[Dict[str, str]]]:
        """在当前会话中执行代码"""
        if not self.docker_available or not self.container:
            return (
                "[Mock Mode] Docker not active. Session simulated.\nVariables from previous steps are NOT preserved.", 
                "", []
            )

        try:
            run_id = str(uuid.uuid4())[:8]
            script_filename = f"script_{run_id}.py"
            plot_filename = f"plot_{run_id}.png"
            container_plot_path = f"/workspace/{plot_filename}"

            # 注入代码文件
            wrapped_code = self._wrap_code_with_plot_saving(code, container_plot_path)
            self._write_file_to_container("/workspace", script_filename, wrapped_code)
            
            # 执行命令 (注意：这里是新的 python 进程，如果需要完全的变量保持，需要用 IPython kernel)
            # 但作为 MVP，文件系统的持久化（如 pip install, 生成的文件）已经比之前强很多了。
            # 为了支持变量保持，OpenDevin 使用了 Jupyter Kernel Gateway，这里我们简化为“文件系统持久化”。
            # 如果用户需要变量保持，可以将变量 pickle dump/load，或者我们只做 Shell 级的持久化。
            cmd = f"timeout {timeout}s python -u /workspace/{script_filename}"
            
            exec_result = self.container.exec_run(cmd, workdir="/workspace")
            
            stdout = exec_result.output.decode("utf-8", errors="replace")
            stderr = ""
            
            if exec_result.exit_code == 124:
                stderr = f"❌ Execution Timed Out (Limit: {timeout}s)"
            elif exec_result.exit_code != 0:
                stderr = stdout # Merge output
            
            # 提取图片
            images = self._extract_image_from_container(container_plot_path)
            
            return stdout, stderr, images
            
        except Exception as e:
            return "", f"System Error: {str(e)}", []

    def execute_command(self, command: str) -> str:
        """[OpenDevin] 执行 Shell 命令 (如 pip install)"""
        if not self.docker_available or not self.container:
            return "[Mock] Command executed successfully."

        try:
            # 简单的 exec_run
            exec_result = self.container.exec_run(command, workdir="/workspace")
            return exec_result.output.decode("utf-8", errors="replace")
        except Exception as e:
            return f"Command failed: {e}"

    def close_session(self):
        """销毁会话"""
        if self.container:
            try:
                logger.info(f"🛑 Closing session: {self.container_name}")
                self.container.remove(force=True)
            except:
                pass
            self.container = None

    # ... (Helpers: _write_file_to_container, _extract_image_from_container, _wrap_code_with_plot_saving remain same)
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
