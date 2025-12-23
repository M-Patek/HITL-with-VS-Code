import docker
import time
import logging
import tarfile
import io
import base64
import os
import uuid
from typing import Tuple, List, Optional, Dict

logger = logging.getLogger("Tools-Sandbox")

class DockerSandbox:
    def __init__(self, image: str = "python:3.9-slim"):
        # [Optimization] 优雅降级：检查 Docker 是否可用
        self.docker_available = False
        try:
            self.client = docker.from_env()
            self.client.ping()
            self.docker_available = True
        except Exception as e:
            logger.warning(f"⚠️ Docker not available: {e}. Entering Mock Mode.")
            self.client = None

        self.image = image
        self.container_name = "swarm_sandbox_runner"
        self.container = None

    def run_code(self, code: str, timeout: int = 30) -> Tuple[str, str, List[Dict[str, str]]]:
        # [Optimization] Mock Mode
        if not self.docker_available:
            return (
                "[Mock Mode] Docker is not running. Code cannot be executed safely.\n(This is a simulated output defined in sandbox.py)", 
                "", 
                []
            )

        try:
            # [Optimization] 懒加载容器，处理容器复用
            try:
                self.container = self.client.containers.get(self.container_name)
                if self.container.status != "running":
                    self.container.start()
            except docker.errors.NotFound:
                self.container = self.client.containers.run(
                    self.image,
                    detach=True,
                    tty=True,
                    name=self.container_name,
                    mem_limit="512m",
                    network_mode="none" 
                )
            
            # [Optimization] 使用 UUID 避免并发文件冲突
            run_id = str(uuid.uuid4())[:8]
            script_filename = f"script_{run_id}.py"
            plot_filename = f"plot_{run_id}.png"
            container_plot_path = f"/tmp/{plot_filename}"

            wrapped_code = self._wrap_code_with_plot_saving(code, container_plot_path)
            self._write_file_to_container("/tmp", script_filename, wrapped_code)
            
            # [Optimization] 增加超时控制 (使用 timeout 命令)
            cmd = f"timeout {timeout}s python -u /tmp/{script_filename}"
            exec_result = self.container.exec_run(cmd)
            
            stdout = exec_result.output.decode("utf-8", errors="replace")
            stderr = ""
            
            # 检查超时状态码 (124 是 timeout 命令的标准退出码)
            if exec_result.exit_code == 124:
                stderr = f"❌ Execution Timed Out (Limit: {timeout}s)"
            elif exec_result.exit_code != 0:
                stderr = stdout # 通常 stderr 也会合并在 output 中
            
            # 提取图片
            images = self._extract_image_from_container(container_plot_path)
            
            # 可选：清理临时文件
            # self.container.exec_run(f"rm /tmp/{script_filename} {container_plot_path}")

            return stdout, stderr, images
            
        except Exception as e:
            return "", f"System Error: {str(e)}", []

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
                member_name = os.path.basename(filepath)
                for m in tar.getmembers():
                    if m.name.endswith(member_name):
                        img_data = tar.extractfile(m).read()
                        b64_img = base64.b64encode(img_data).decode('utf-8')
                        images.append({"type": "image", "filename": member_name, "data": f"data:image/png;base64,{b64_img}"})
                        break
        except: pass
        return images

    def _wrap_code_with_plot_saving(self, code: str, save_path: str) -> str:
        if "matplotlib" in code or "plt." in code:
            # 动态插入保存路径
            header = f"import matplotlib\nmatplotlib.use('Agg')\nimport matplotlib.pyplot as plt\n"
            footer = f"\ntry:\n    if plt.get_fignums():\n        plt.savefig('{save_path}')\nexcept: pass"
            return header + code + footer
        return code

# 全局方法，供 nodes.py 调用
def run_python_code(code: str):
    sandbox = DockerSandbox()
    stdout, stderr, images = sandbox.run_code(code)
    return {
        "stdout": stdout,
        "stderr": stderr,
        "images": images,
        "returncode": 0 if not stderr else 1
    }
