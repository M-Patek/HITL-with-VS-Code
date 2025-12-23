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
    def __init__(self, task_id: str, image: str = "python:3.9-slim"):
        self.task_id = task_id
        self.image = image
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
            self.container = self.client.containers.run(
                self.image,
                detach=True,
                tty=True,
                name=self.container_name,
                entrypoint="tail -f /dev/null", 
                mem_limit="512m",
                network_mode="bridge" 
            )
            self.container.exec_run("mkdir -p /workspace")

        except Exception as e:
            logger.error(f"Failed to start sandbox session: {e}")
            self.docker_available = False 

    def execute_code(self, code: str, timeout: int = 30) -> Tuple[str, str, List[Dict[str, str]]]:
        """在当前会话中执行代码"""
        if not self.docker_available or not self.container:
            # [Fix] Explicit failure for Mock Mode to prevent hallucination
            return (
                "", 
                "[System] Docker unavailable. Code execution skipped. Please enable Docker to run code safely.",
                []
            )

        try:
            run_id = str(uuid.uuid4())[:8]
            script_filename = f"script_{run_id}.py"
            plot_filename = f"plot_{run_id}.png"
            container_plot_path = f"/workspace/{plot_filename}"

            wrapped_code = self._wrap_code_with_plot_saving(code, container_plot_path)
            self._write_file_to_container("/workspace", script_filename, wrapped_code)
            
            cmd = f"timeout {timeout}s python -u /workspace/{script_filename}"
            exec_result = self.container.exec_run(cmd, workdir="/workspace")
            
            stdout = exec_result.output.decode("utf-8", errors="replace")
            stderr = ""
            
            if exec_result.exit_code == 124:
                stderr = f"❌ Execution Timed Out (Limit: {timeout}s)"
            elif exec_result.exit_code != 0:
                stderr = stdout 
            
            images = self._extract_image_from_container(container_plot_path)
            return stdout, stderr, images
            
        except Exception as e:
            return "", f"System Error: {str(e)}", []

    def execute_command(self, command: str) -> str:
        if not self.docker_available or not self.container:
             return "[System] Docker unavailable. Command execution skipped."

        try:
            exec_result = self.container.exec_run(command, workdir="/workspace")
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
